"""Policy gate + C1 fix tests for update_booking (T12-T18).

Tests cover:
- T12: C1 regression — services=None with pre_resolved_service_ids does NOT raise TypeError
- T14: gate fires for new customer (policy_accepted_at=None, slot_iso set, policy_accepted=False)
- T15: gate fires for returning customer with stale policy version
- T16: gate CLEARS on policy_accepted=True — flow continues past gate
- T17: gate emits policy_escalation_required when policy_rejection_count >= 2
- T18: gate skipped for customer with current accepted version

All tests use patched DB helpers — no live DB connection required.
Refs: Spec S-1, S-3, S-4, S-5, S-8, S-10 / Design §2.1-2.3 / Tasks T12-T18
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_SERVICE_ID = str(uuid4())
FAKE_STYLIST_ID = str(uuid4())
POLICY_VERSION = "1.0"
POLICY_URL = "https://atrevetepeluqueria.com/politica-privacidad/"


def _next_tuesday() -> str:
    """Return the next Tuesday as ISO date string (never a closed Sunday)."""
    today = date.today()
    days_ahead = (1 - today.weekday()) % 7  # 1 = Tuesday
    if days_ahead < 4:  # must be at least 4 days ahead to satisfy advance policy
        days_ahead += 7
    return (today + timedelta(days=days_ahead)).isoformat()


FUTURE_DATE = _next_tuesday()
FUTURE_SLOT_ISO = f"{FUTURE_DATE}T10:00:00+02:00"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def parse_response(raw: str) -> dict:
    return json.loads(raw)


def _make_session_ctx():
    """Build a fake async session context manager."""
    session_mock = AsyncMock()
    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=session_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)
    return ctx_mock, session_mock


def _make_check_avail_message(slot_iso: str, stylist_id: str) -> object:
    """Build a fake check_availability ToolMessage confirming a slot."""
    msg = MagicMock()
    msg.name = "check_availability"
    msg.content = json.dumps(
        {
            "status": "ok",
            "payload": {
                "slots": [{"start_iso": slot_iso, "stylist_id": stylist_id}],
                "exact_match": True,
            },
        }
    )
    return msg


def _make_settings_mock(policy_version: str = POLICY_VERSION, policy_url: str = POLICY_URL):
    """Build a settings mock with policy fields."""
    from shared.config import Settings as _Settings

    s = MagicMock(spec=_Settings)
    s.POLICY_VERSION = policy_version
    s.POLICY_URL = policy_url
    return s


def _make_customer_state(
    *,
    policy_accepted_at=None,
    policy_version=None,
) -> MagicMock:
    """Build a minimal customer-state mock for policy gate."""
    c = MagicMock()
    c.policy_accepted_at = policy_accepted_at
    c.policy_version = policy_version
    return c


@contextmanager
def _standard_patches(
    stylist_id=None,
    settings_mock=None,
    customer_state_in_db=None,
    session_ctx=None,
):
    """Context manager applying the standard set of patches needed for gate tests."""
    from database.models import ServiceCategory

    sid = stylist_id or uuid4()
    ctx = session_ctx or _make_session_ctx()[0]
    settings = settings_mock or _make_settings_mock()

    # session.get() returns customer_state_in_db (for the policy gate DB lookup)
    inner_session = MagicMock()
    inner_ctx = MagicMock()
    inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
    inner_ctx.__aexit__ = AsyncMock(return_value=False)

    if customer_state_in_db is not None:
        inner_session.get = AsyncMock(return_value=customer_state_in_db)

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            AsyncMock(return_value=([FAKE_SERVICE_ID], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            AsyncMock(return_value=([FAKE_SERVICE_ID], [], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            AsyncMock(return_value={ServiceCategory.HAIRDRESSING}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            AsyncMock(return_value=("ok", None, [])),
        ),
        patch("agent.tools._booking_helpers._resolve_stylist", AsyncMock(return_value=sid)),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            AsyncMock(return_value=[]),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            MagicMock(return_value=("Juan", "García")),
        ),
        patch("database.connection.get_async_session", return_value=inner_ctx),
        patch("agent.tools.update_booking.get_settings", return_value=settings),
        patch("agent.tools._booking_validators.is_date_closed", AsyncMock(return_value=False)),
    ):
        yield inner_session


# ---------------------------------------------------------------------------
# T12 — C1 regression: services=None with pre_resolved_service_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c1_services_none_no_crash():
    """T12: services=None + pre_resolved_service_ids=[uuid] must NOT crash with TypeError.

    Before C1 fix, iteration over `services` (None) raises TypeError at the
    audience/variant disambiguation loops. After fix, function returns a valid
    ToolResponse without crashing.
    Spec S-10 / Design §2.4
    """
    from agent.tools.update_booking import _update_booking_impl
    from database.models import ServiceCategory

    stylist_id = uuid4()
    inner_session = AsyncMock()
    inner_ctx = MagicMock()
    inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
    inner_ctx.__aexit__ = AsyncMock(return_value=False)

    # Session execute for pre_resolved UUID validation
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [(FAKE_SERVICE_ID,)]
    inner_session.execute = AsyncMock(return_value=result_mock)

    settings = _make_settings_mock()

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            AsyncMock(return_value=([FAKE_SERVICE_ID], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            AsyncMock(return_value=([FAKE_SERVICE_ID], [], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            AsyncMock(return_value={ServiceCategory.HAIRDRESSING}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            AsyncMock(return_value=("ok", None, [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            AsyncMock(return_value=stylist_id),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            AsyncMock(return_value=[]),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            MagicMock(return_value=("Juan", "García")),
        ),
        patch("database.connection.get_async_session", return_value=inner_ctx),
        patch("agent.tools.update_booking.get_settings", return_value=settings),
        patch("agent.tools._booking_validators.is_date_closed", AsyncMock(return_value=False)),
    ):
        # services=None — before C1 fix this raises TypeError on iteration
        result_json = await _update_booking_impl(
            services=None,  # ← the C1 bug: None passed here
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=FUTURE_DATE,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=False,
            extras_asked=False,
            notes_asked=False,
            customer_known=False,
            slot_iso=None,
            variant_resolved=False,
            pre_resolved_service_ids=[FAKE_SERVICE_ID],
            messages=[],
        )

    result = parse_response(result_json)
    # Result must be a valid ToolResponse — not a crash
    assert "next_step" in result, f"Expected valid ToolResponse, got: {result}"
    # Must not have crashed with an internal error
    assert "internal:" not in " ".join(result.get("errors", [])), (
        f"Unexpected internal error: {result}"
    )


# ---------------------------------------------------------------------------
# T14 — gate fires for new customer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_gate_new_customer():
    """T14: new customer (policy_accepted_at=None), slot_iso set, policy_accepted=False
    → next_step == 'policy_acceptance_required' with correct payload keys.

    Spec S-1, S-8 / Design §2.2
    """
    from agent.tools.update_booking import _update_booking_impl

    stylist_id = uuid4()
    check_avail_msg = _make_check_avail_message(FUTURE_SLOT_ISO, str(stylist_id))

    # Customer has NOT accepted the policy (policy_accepted_at=None)
    customer_state = _make_customer_state(policy_accepted_at=None, policy_version=None)
    settings = _make_settings_mock()

    with _standard_patches(
        stylist_id=stylist_id,
        settings_mock=settings,
        customer_state_in_db=customer_state,
    ):
        result_json = await _update_booking_impl(
            services=["corte"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=FUTURE_DATE,
            audience=None,
            customer_full_name="Juan García",
            notes=None,
            no_more_services=True,
            extras_asked=True,
            notes_asked=True,
            customer_known=True,
            slot_iso=FUTURE_SLOT_ISO,
            variant_resolved=False,
            pre_resolved_service_ids=None,
            messages=[check_avail_msg],
            policy_accepted=False,
            policy_rejection_count=0,
            customer_id=str(uuid4()),  # customer_id passed so gate can fetch
        )

    result = parse_response(result_json)
    assert result["next_step"] == "policy_acceptance_required", (
        f"Expected policy_acceptance_required, got: {result}"
    )
    payload = result.get("payload", {})
    assert "policy_url" in payload, f"Expected policy_url in payload: {payload}"
    assert "policy_version" in payload, f"Expected policy_version in payload: {payload}"
    assert "policy_rejection_count" in payload, (
        f"Expected policy_rejection_count in payload: {payload}"
    )


# ---------------------------------------------------------------------------
# T15 — gate fires for stale version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_gate_stale_version():
    """T15: returning customer with policy_version='0.9', settings.POLICY_VERSION='1.0'
    → next_step == 'policy_acceptance_required'.

    Spec S-5 / Design §2.2
    """
    from agent.tools.update_booking import _update_booking_impl

    stylist_id = uuid4()
    check_avail_msg = _make_check_avail_message(FUTURE_SLOT_ISO, str(stylist_id))

    # Customer has accepted but with old version
    customer_state = _make_customer_state(
        policy_accepted_at=datetime.now(UTC) - timedelta(days=30),
        policy_version="0.9",  # stale — settings is "1.0"
    )
    settings = _make_settings_mock()

    with _standard_patches(
        stylist_id=stylist_id,
        settings_mock=settings,
        customer_state_in_db=customer_state,
    ):
        result_json = await _update_booking_impl(
            services=["corte"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=FUTURE_DATE,
            audience=None,
            customer_full_name="Juan García",
            notes=None,
            no_more_services=True,
            extras_asked=True,
            notes_asked=True,
            customer_known=True,
            slot_iso=FUTURE_SLOT_ISO,
            variant_resolved=False,
            pre_resolved_service_ids=None,
            messages=[check_avail_msg],
            policy_accepted=False,
            policy_rejection_count=0,
            customer_id=str(uuid4()),
        )

    result = parse_response(result_json)
    assert result["next_step"] == "policy_acceptance_required", (
        f"Expected policy_acceptance_required for stale version, got: {result}"
    )


# ---------------------------------------------------------------------------
# T16 — gate clears on policy_accepted=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_gate_cleared_on_acceptance():
    """T16: customer needs policy, policy_accepted=True → gate clears, flow continues.

    next_step should NOT be policy_acceptance_required.
    collected should contain policy_accepted=True.
    Spec S-1 / Design §2.2
    """
    from agent.tools.update_booking import _update_booking_impl

    stylist_id = uuid4()
    check_avail_msg = _make_check_avail_message(FUTURE_SLOT_ISO, str(stylist_id))

    customer_state = _make_customer_state(policy_accepted_at=None, policy_version=None)
    settings = _make_settings_mock()

    with _standard_patches(
        stylist_id=stylist_id,
        settings_mock=settings,
        customer_state_in_db=customer_state,
    ):
        result_json = await _update_booking_impl(
            services=["corte"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=FUTURE_DATE,
            audience=None,
            customer_full_name="Juan García",
            notes=None,
            no_more_services=True,
            extras_asked=True,
            notes_asked=True,
            customer_known=True,
            slot_iso=FUTURE_SLOT_ISO,
            variant_resolved=False,
            pre_resolved_service_ids=None,
            messages=[check_avail_msg],
            policy_accepted=True,  # ← gate should clear
            policy_rejection_count=0,
            customer_id=str(uuid4()),
        )

    result = parse_response(result_json)
    assert result["next_step"] != "policy_acceptance_required", (
        f"Gate should clear when policy_accepted=True, got: {result}"
    )
    # Gate cleared: collected should carry the flag forward
    collected = result.get("collected", {})
    assert collected.get("policy_accepted") is True, (
        f"Expected collected.policy_accepted=True, got collected: {collected}"
    )


# ---------------------------------------------------------------------------
# T17 — escalation at rejection_count >= 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_gate_escalation():
    """T17: policy_rejection_count=2, customer needs policy, policy_accepted=False
    → next_step == 'policy_escalation_required' with reason='policy_rejection'.

    Spec S-3 / Design §2.2
    """
    from agent.tools.update_booking import _update_booking_impl

    stylist_id = uuid4()
    check_avail_msg = _make_check_avail_message(FUTURE_SLOT_ISO, str(stylist_id))

    customer_state = _make_customer_state(policy_accepted_at=None, policy_version=None)
    settings = _make_settings_mock()

    with _standard_patches(
        stylist_id=stylist_id,
        settings_mock=settings,
        customer_state_in_db=customer_state,
    ):
        result_json = await _update_booking_impl(
            services=["corte"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=FUTURE_DATE,
            audience=None,
            customer_full_name="Juan García",
            notes=None,
            no_more_services=True,
            extras_asked=True,
            notes_asked=True,
            customer_known=True,
            slot_iso=FUTURE_SLOT_ISO,
            variant_resolved=False,
            pre_resolved_service_ids=None,
            messages=[check_avail_msg],
            policy_accepted=False,
            policy_rejection_count=2,  # ← at threshold → escalate
            customer_id=str(uuid4()),
        )

    result = parse_response(result_json)
    assert result["next_step"] == "policy_escalation_required", (
        f"Expected policy_escalation_required at count=2, got: {result}"
    )
    payload = result.get("payload", {})
    assert payload.get("reason") == "policy_rejection", (
        f"Expected reason='policy_rejection' in payload: {payload}"
    )


# ---------------------------------------------------------------------------
# T18 — gate skipped for customer with current accepted version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_gate_skipped_current_version():
    """T18: customer.policy_accepted_at set AND policy_version == settings.POLICY_VERSION
    → gate NOT triggered; next_step is NOT policy_acceptance_required.

    Spec S-4 / Design §2.2
    """
    from agent.tools.update_booking import _update_booking_impl

    stylist_id = uuid4()
    check_avail_msg = _make_check_avail_message(FUTURE_SLOT_ISO, str(stylist_id))

    # Customer has already accepted the current version
    customer_state = _make_customer_state(
        policy_accepted_at=datetime.now(UTC) - timedelta(days=5),
        policy_version="1.0",  # matches settings
    )
    settings = _make_settings_mock()

    with _standard_patches(
        stylist_id=stylist_id,
        settings_mock=settings,
        customer_state_in_db=customer_state,
    ):
        result_json = await _update_booking_impl(
            services=["corte"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=FUTURE_DATE,
            audience=None,
            customer_full_name="Juan García",
            notes=None,
            no_more_services=True,
            extras_asked=True,
            notes_asked=True,
            customer_known=True,
            slot_iso=FUTURE_SLOT_ISO,
            variant_resolved=False,
            pre_resolved_service_ids=None,
            messages=[check_avail_msg],
            policy_accepted=False,  # even with False — gate should skip
            policy_rejection_count=0,
            customer_id=str(uuid4()),
        )

    result = parse_response(result_json)
    assert result["next_step"] not in (
        "policy_acceptance_required",
        "policy_escalation_required",
    ), f"Gate should be skipped for current-version customer, got: {result}"
    # All other gates pass → should reach booking_ready
    assert result["next_step"] == "booking_ready", (
        f"Expected booking_ready after gate skip, got: {result}"
    )
