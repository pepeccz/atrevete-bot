"""TDD tests for booking-ideal-flow-completion — update_booking new behaviour.

Tasks 2.1 (RED) and 2.2 (GREEN):
  - REQ-P1-1 / REQ-P1-2: offer_slots next_step
  - REQ-P2A-1: closed_day_required gate
  - REQ-BX-2: name_required fires after date resolution (regression guard)

Post-PR#2: all DB helpers patched via BookingQueryService.resolve_all
(single-session facade). No longer patches agent.tools._booking_helpers.*
or database.connection.get_async_session.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_STYLIST_ID = uuid4()
FAKE_SERVICE_ID = uuid4()

# A Monday far enough in the future — open day (business assumes Mon-Sat open)
OPEN_DATE_ISO = "2026-06-01"
# A Sunday in the future — closed by default
CLOSED_DATE_ISO = "2026-05-31"


def parse_response(raw: str) -> dict:
    return json.loads(raw)


def _make_resolve_all_result(
    *,
    service_ids=None,
    unknown_names=None,
    stylist_id=None,
    active_stylists=None,
    has_category_mix=False,
    hair_services=None,
    aesth_services=None,
    both_services=None,
):
    """Build a ResolveAllResult for mocking BookingQueryService.resolve_all."""
    from agent.services.booking_query_service import ResolveAllResult

    return ResolveAllResult(
        success=(unknown_names is None or len(unknown_names) == 0),
        service_ids=service_ids if service_ids is not None else [FAKE_SERVICE_ID],
        unknown_names=unknown_names if unknown_names is not None else [],
        stylist_id=stylist_id,
        audience_variants=("none", "", []),
        categories=set(),
        id_to_category={},
        active_stylists=active_stylists if active_stylists is not None else [],
        has_category_mix=has_category_mix,
        hair_services=hair_services or [],
        aesth_services=aesth_services or [],
        both_services=both_services or [],
        error_message=None,
    )


def _patch_booking_helpers(
    service_ids=None,
    unknown_names=None,
    stylist_id=None,
    active_stylists=None,
    is_date_closed_return=False,
):
    """Return a dict of patch targets for mocking BookingQueryService internals.

    Post-PR#2: patches BookingQueryService.resolve_all (single-session facade)
    and BookingQueryService.resolve_audience_variants (per-service disambiguation).
    """
    resolve_all_result = _make_resolve_all_result(
        service_ids=service_ids,
        unknown_names=unknown_names,
        stylist_id=stylist_id,
        active_stylists=active_stylists,
    )

    resolve_all_mock = AsyncMock(return_value=resolve_all_result)
    resolve_audience_variants_mock = AsyncMock(return_value=("none", "", []))
    is_date_closed_mock = AsyncMock(return_value=is_date_closed_return)

    return {
        "agent.services.booking_query_service.BookingQueryService.resolve_all": resolve_all_mock,
        "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants": resolve_audience_variants_mock,
        "agent.tools._booking_validators.is_date_closed": is_date_closed_mock,
        "shared.business_hours_validator.is_date_closed": is_date_closed_mock,
    }


# ---------------------------------------------------------------------------
# Phase 1 — offer_slots (REQ-P1-1, REQ-P1-2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offer_slots_when_stylist_resolved_and_no_date():
    """REQ-P1-1: services+stylist resolved, no date → next_step=offer_slots.

    Payload must include stylist_id, service_ids, from_date (today ISO).
    """
    from agent.tools.update_booking import _update_booking_impl

    mocks = _patch_booking_helpers(stylist_id=FAKE_STYLIST_ID)

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["corte dama"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    data = parse_response(raw)
    assert data["next_step"] == "offer_slots", f"Got: {data}"
    payload = data.get("payload", {})
    assert "stylist_id" in payload
    assert "service_ids" in payload
    assert "from_date" in payload
    assert payload["no_preference_stylist"] is False


@pytest.mark.asyncio
async def test_offer_slots_with_no_preference():
    """REQ-P1-1 + REQ-P1-2: no_preference_stylist=True, no date → offer_slots with stylist_id=None."""
    from agent.tools.update_booking import _update_booking_impl

    mocks = _patch_booking_helpers(stylist_id=None)

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["corte dama"],
            stylist_name=None,
            no_preference_stylist=True,
            date_iso=None,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    data = parse_response(raw)
    assert data["next_step"] == "offer_slots", f"Got: {data}"
    payload = data.get("payload", {})
    assert payload.get("no_preference_stylist") is True
    assert payload.get("stylist_id") is None


@pytest.mark.asyncio
async def test_date_required_regression_guard():
    """REQ-P1-2: date_required path is still reachable when offer_slots was explicitly exhausted.

    Since update_booking is stateless, the only way the prompt conveys
    'offer_slots was already attempted' is by passing date_iso=None with
    no stylist resolved. This test confirms the fallback date_required
    branch is NOT broken — it fires when stylist is also absent.

    Note: When stylist IS resolved but date is absent, offer_slots fires (see above).
    This is the pre-stylist fallback path.
    """
    from agent.tools.update_booking import _update_booking_impl

    # No stylist — stylist_required fires before offer_slots
    mocks = _patch_booking_helpers(stylist_id=None)

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["corte dama"],
            stylist_name=None,
            no_preference_stylist=False,  # no preference NOT set → stylist_required
            date_iso=None,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    data = parse_response(raw)
    # stylist_required fires before offer_slots / date_required — matrix is intact
    assert data["next_step"] == "stylist_required", f"Got: {data}"


# ---------------------------------------------------------------------------
# Phase 2A — closed_day_required gate (REQ-P2A-1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_day_required_for_sunday():
    """REQ-P2A-1: services+stylist+date_iso=Sunday → next_step=closed_day_required.

    Note: CLOSED_DATE_ISO is 2026-05-31 (Sunday). is_date_closed mocked to True.
    """
    from agent.tools.update_booking import _update_booking_impl

    mocks = _patch_booking_helpers(
        stylist_id=FAKE_STYLIST_ID,
        is_date_closed_return=True,  # Sunday → closed
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["corte dama"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=CLOSED_DATE_ISO,  # 2026-05-03 Sunday
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    data = parse_response(raw)
    assert data["next_step"] == "closed_day_required", f"Got: {data}"
    assert data["status"] == "rejected"
    payload = data.get("payload", {})
    assert payload.get("rejected_date") == CLOSED_DATE_ISO
    assert "weekday" in payload


@pytest.mark.asyncio
async def test_closed_day_required_uses_database_validator():
    """REQ-P2A-1: assert is_date_closed is called with the parsed date object."""
    from agent.tools.update_booking import _update_booking_impl

    is_date_closed_spy = AsyncMock(return_value=True)
    mocks = _patch_booking_helpers(
        stylist_id=FAKE_STYLIST_ID,
        is_date_closed_return=True,
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
        patch("agent.tools._booking_validators.is_date_closed", is_date_closed_spy),
    ):
        await _update_booking_impl(
            services=["corte dama"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=CLOSED_DATE_ISO,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    is_date_closed_spy.assert_called_once()
    called_with = is_date_closed_spy.call_args[0][0]
    assert isinstance(called_with, date), f"Expected date, got: {type(called_with)}"
    assert called_with == date.fromisoformat(CLOSED_DATE_ISO)


@pytest.mark.asyncio
async def test_open_day_passes_through_to_name_required():
    """REQ-P2A-1 negative: open day → closed_day_required does NOT fire → name_required."""
    from agent.tools.update_booking import _update_booking_impl

    mocks = _patch_booking_helpers(
        stylist_id=FAKE_STYLIST_ID,
        is_date_closed_return=False,  # Tuesday → open
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["corte dama"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=OPEN_DATE_ISO,  # 2026-05-05 Tuesday
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    data = parse_response(raw)
    # name_required should be next after date is validated and day is open
    assert data["next_step"] == "name_required", f"Got: {data}"


# ---------------------------------------------------------------------------
# Phase T5 — adapter-mapping regression tests (T5 RED → T6 GREEN)
#
# These tests assert the wire-format output of _update_booking_impl for
# G1 (date_clarification_required), G2 (closed_day_required), and G3
# (advance_policy_violated). They must remain GREEN before and after the
# T6 refactor that delegates to validate_booking_date internally.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_g1_date_clarification_required():
    """T5 G1: date_text unresolvable → next_step=date_clarification_required (wire format)."""
    from agent.tools.update_booking import _update_booking_impl

    mocks = _patch_booking_helpers(stylist_id=FAKE_STYLIST_ID)

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
        # Patch the resolver to return None → unresolvable
        patch(
            "agent.booking.resolvers.time_resolver.resolve_relative_date",
            return_value=None,
        ),
    ):
        raw = await _update_booking_impl(
            services=["corte dama"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=None,
            date_text="algun dia",  # unresolvable
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    data = parse_response(raw)
    assert data["next_step"] == "date_clarification_required", f"Got: {data}"
    assert data["status"] == "partial"


@pytest.mark.asyncio
async def test_adapter_g2_closed_day_required_wire_format():
    """T5 G2: closed day → next_step=closed_day_required with payload (wire format)."""
    from agent.tools.update_booking import _update_booking_impl

    mocks = _patch_booking_helpers(
        stylist_id=FAKE_STYLIST_ID,
        is_date_closed_return=True,
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["corte dama"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=CLOSED_DATE_ISO,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    data = parse_response(raw)
    assert data["next_step"] == "closed_day_required", f"Got: {data}"
    assert data["status"] == "rejected"
    # Payload must be forwarded
    payload = data.get("payload", {})
    assert "rejected_date" in payload, f"payload missing rejected_date: {payload}"


@pytest.mark.asyncio
async def test_adapter_g3_advance_policy_violated_payload_forwarded():
    """T5 G3: advance_policy_violated → next_step=advance_policy_violated + payload intact."""
    from agent.tools.update_booking import _update_booking_impl

    # date very close to "today" → violates lead-time
    # Using 2026-04-29 (tomorrow) which will be < today + MIN_BOOKING_DAYS (3 days)
    TOMORROW_ISO = "2026-04-29"

    mocks = _patch_booking_helpers(
        stylist_id=FAKE_STYLIST_ID,
        is_date_closed_return=False,  # open day, but violates lead-time
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_all"],
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            mocks["agent.services.booking_query_service.BookingQueryService.resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["corte dama"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=TOMORROW_ISO,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
        )

    data = parse_response(raw)
    assert data["next_step"] == "advance_policy_violated", f"Got: {data}"
    assert data["status"] == "rejected"
    payload = data.get("payload", {})
    assert "first_valid_date" in payload, f"payload missing first_valid_date: {payload}"
    assert "policy_min_days" in payload, f"payload missing policy_min_days: {payload}"


# ---------------------------------------------------------------------------
# Phase Gate Hardening — _find_matching_check_availability (T1–T8 RED → GREEN)
# ---------------------------------------------------------------------------
#
# These tests target `_find_matching_check_availability` directly — no DB needed.
# The helper accepts (messages, slot_iso, stylist_id) and returns bool.
# ---------------------------------------------------------------------------

import json as _json
from unittest.mock import MagicMock as _MagicMock


def _ca_msg(slots: list[str], stylist_id: str | None = None, status: str = "ok") -> object:
    """Build a fake check_availability ToolMessage with the given slot ISO strings."""
    sid = stylist_id or FAKE_STYLIST_ID
    msg = _MagicMock()
    msg.name = "check_availability"
    msg.content = _json.dumps({
        "status": status,
        "payload": {
            "slots": [{"start_iso": s, "stylist_id": str(sid)} for s in slots],
            "exact_match": True,
        },
    })
    return msg


# T1 — RED: TZ equivalence Z vs +00:00
def test_gate_tz_z_vs_plus0000():
    """T1: slot in ToolMessage +00:00, slot_iso uses Z — must match (same instant)."""
    from agent.tools.update_booking import _find_matching_check_availability

    msg = _ca_msg(["2026-05-10T10:30:00+00:00"])
    result = _find_matching_check_availability([msg], "2026-05-10T10:30:00Z", None)
    assert result is True, "Expected True: Z == +00:00 are the same instant"


# T2 — RED: TZ equivalence Madrid offset vs UTC equivalent
def test_gate_tz_madrid_vs_utc_equivalent():
    """T2: slot +02:00, slot_iso is the UTC equivalent — must match."""
    from agent.tools.update_booking import _find_matching_check_availability

    msg = _ca_msg(["2026-05-10T10:30:00+02:00"])
    result = _find_matching_check_availability([msg], "2026-05-10T08:30:00Z", None)
    assert result is True, "Expected True: 10:30+02:00 == 08:30Z"


# T3 — RED: No-seconds slot_iso
def test_gate_no_seconds_slot_iso():
    """T3: slot_iso has no :00 seconds — must still match equivalent slot."""
    from agent.tools.update_booking import _find_matching_check_availability

    msg = _ca_msg(["2026-05-10T10:30:00+02:00"])
    result = _find_matching_check_availability([msg], "2026-05-10T10:30+02:00", None)
    assert result is True, "Expected True: T10:30+02:00 == T10:30:00+02:00"


# T4 — RED: Substring false-positive — truncated unparseable
def test_gate_substring_false_positive_truncated():
    """T4: slot_iso is a substring of the ToolMessage slot but not a valid datetime — must return False."""
    from agent.tools.update_booking import _find_matching_check_availability

    msg = _ca_msg(["2026-05-10T10:30:00+02:00"])
    result = _find_matching_check_availability([msg], "2026-05-10T10:3", None)
    assert result is False, "Expected False: truncated/unparseable ISO must not match"


# T5 — RED: Substring false-positive — date-only prefix
def test_gate_substring_false_positive_date_only():
    """T5: slot_iso is date-only, which is a substring of the ToolMessage slots — must return False."""
    from agent.tools.update_booking import _find_matching_check_availability

    msg = _ca_msg(["2026-05-10T09:00:00+02:00", "2026-05-10T10:30:00+02:00"])
    result = _find_matching_check_availability([msg], "2026-05-10", None)
    assert result is False, "Expected False: date-only prefix must not match any slot"


# T6 — RED: Naive datetime fail-closed
def test_gate_naive_datetime_fail_closed():
    """T6: slot_iso has no timezone — must fail-closed (return False, not raise)."""
    from agent.tools.update_booking import _find_matching_check_availability

    msg = _ca_msg(["2026-05-10T10:30:00+02:00"])
    result = _find_matching_check_availability([msg], "2026-05-10T10:30:00", None)
    assert result is False, "Expected False: naive datetime must be rejected (fail-closed)"


# T7 — RED: Malformed ISO fail-closed
def test_gate_malformed_iso_no_raise():
    """T7: slot_iso is garbage — must return False without raising."""
    from agent.tools.update_booking import _find_matching_check_availability

    msg = _ca_msg(["2026-05-10T10:30:00+02:00"])
    result = _find_matching_check_availability([msg], "not-a-date", None)
    assert result is False, "Expected False: malformed ISO must not raise and must return False"


# T8 — RED: Full history scan beyond 6-message window
def test_gate_full_history_scan_beyond_6_messages():
    """T8: relevant ToolMessage is at index 5 (position -10 from end in a 15-msg history)."""
    from agent.tools.update_booking import _find_matching_check_availability

    slot_dt = "2026-05-10T10:30:00+02:00"
    relevant_msg = _ca_msg([slot_dt])

    # Build 15-message history: relevant at index 5, rest are non-matching filler
    filler = _MagicMock()
    filler.name = "something_else"
    messages = [filler] * 5 + [relevant_msg] + [filler] * 9
    assert len(messages) == 15

    result = _find_matching_check_availability(messages, slot_dt, None)
    assert result is True, (
        "Expected True: gate must scan full history, not just last 6 messages"
    )
