"""Tests for update_booking date_iso derivation from slot_iso.

Spec: update-booking-date-iso-sync — 4 acceptance cases.

Cases 1 and 3 are RED against the current codebase: they FAIL before the fix
in agent/tools/update_booking.py (lines 765-771) and PASS after (GREEN).
Cases 2 and 4 are already GREEN.

No DB access required — all resolver and DB helpers are mocked.
Root cause: when the customer selects a slot by option number after
advance_policy_violated, the LLM sets slot_iso but carries a stale date_iso
(today). validate_booking_date fires G3 a second time → rejection strike →
escalate called instead of book. Fix: derive date_iso from slot_iso before
the "no date" early-return and before validate_booking_date.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Constants — computed once at import time; stable for the test session.
# ---------------------------------------------------------------------------

FAKE_STYLIST_ID = str(uuid4())
TODAY_ISO = date.today().isoformat()
FUTURE_DATE = (date.today() + timedelta(days=4)).isoformat()  # 4 days out — passes G3 (min=3)
FUTURE_ISO = f"{FUTURE_DATE}T10:00:00+02:00"                  # TZ-aware slot in Europe/Madrid


def parse(raw: str) -> dict:
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


def _make_session_ctx():
    session_mock = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_ok_fk():
    r = MagicMock()
    r.ok = True
    r.missing_ids = []
    r.payload = {}
    return r


def _make_offered_slots():
    """Return recently_offered_slots with FUTURE_ISO + FAKE_STYLIST_ID."""
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    return [
        {
            "start_iso": FUTURE_ISO,
            "stylist_id": FAKE_STYLIST_ID,
            "expires_at": expires,
            "turn_index": 0,
        }
    ]


@pytest.fixture
def mock_helpers():
    """Patch all DB and resolver helpers so _update_booking_impl runs without a real DB."""
    ctx = _make_session_ctx()
    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["svc-uuid-001"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            new=AsyncMock(return_value=(["svc-uuid-001"], [], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            new=AsyncMock(return_value=FAKE_STYLIST_ID),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            new=AsyncMock(return_value=[{"id": FAKE_STYLIST_ID, "name": "Marta Test"}]),
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            new=MagicMock(return_value=("Ana", "García")),
        ),
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "shared.business_hours_validator.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "agent.tools.update_booking.validate_service_ids_exist",
            new=AsyncMock(return_value=_make_ok_fk()),
        ),
        patch(
            "agent.tools.update_booking.validate_stylist_id_exists",
            new=AsyncMock(return_value=_make_ok_fk()),
        ),
        patch(
            "agent.tools.update_booking._load_lead_time_min_days",
            new=AsyncMock(return_value=3),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Case 1 (RED → GREEN): stale date_iso (today) + valid future slot_iso
# ---------------------------------------------------------------------------


class TestStaleDateDerivedFromSlot:
    """G3 fires on stale date_iso=today; fix derives date_iso from slot_iso → G3 clears."""

    @pytest.mark.asyncio
    async def test_date_iso_derived_when_stale_no_advance_policy_violation(self, mock_helpers):
        from agent.tools.update_booking import _update_booking_impl

        result = parse(
            await _update_booking_impl(
                services=["corte dama"],
                stylist_name="Marta Test",
                no_preference_stylist=False,
                date_iso=TODAY_ISO,           # stale — today → G3 fires without fix
                date_text=None,
                audience=None,
                no_more_services=True,
                extras_asked=True,
                customer_full_name="Ana García",
                customer_known=True,
                notes_asked=True,
                slot_iso=FUTURE_ISO,          # 4 days out — fix derives date_iso from here
                recently_offered_slots=_make_offered_slots(),
                messages=[],
                policy_accepted=True,
            )
        )

        # After fix: date_iso derived from slot_iso (today+4) → G3 clears → pre-book gate.
        # Before fix (RED): validate_booking_date(today) fires G3 → advance_policy_violated.
        assert result["next_step"] == "pre_book_validation_required", (
            f"Expected pre_book_validation_required after date_iso derived from slot_iso, "
            f"got: {result['next_step']!r}. Full payload: {result}"
        )


# ---------------------------------------------------------------------------
# Case 2 (GREEN from start): correct date_iso + matching slot_iso → idempotent
# ---------------------------------------------------------------------------


class TestCorrectDateIdempotent:
    """Derivation is a no-op when date_iso already matches the slot_iso date."""

    @pytest.mark.asyncio
    async def test_derivation_noop_when_date_already_correct(self, mock_helpers):
        from agent.tools.update_booking import _update_booking_impl

        result = parse(
            await _update_booking_impl(
                services=["corte dama"],
                stylist_name="Marta Test",
                no_preference_stylist=False,
                date_iso=FUTURE_DATE,         # already correct — matches slot date
                date_text=None,
                audience=None,
                no_more_services=True,
                extras_asked=True,
                customer_full_name="Ana García",
                customer_known=True,
                notes_asked=True,
                slot_iso=FUTURE_ISO,          # same date as date_iso
                recently_offered_slots=_make_offered_slots(),
                messages=[],
                policy_accepted=True,
            )
        )

        # Derivation sets date_iso to the same value — behavior unchanged.
        assert result["next_step"] == "pre_book_validation_required", (
            f"Expected pre_book_validation_required (idempotent derivation), got: {result}"
        )


# ---------------------------------------------------------------------------
# Case 3 (RED → GREEN): null date_iso + valid slot_iso → bypass "no date" early return
# ---------------------------------------------------------------------------


class TestNullDateDerivedFromSlot:
    """With date_iso=None and slot_iso set, fix derives date_iso and bypasses offer_slots."""

    @pytest.mark.asyncio
    async def test_date_iso_derived_from_slot_bypasses_no_date_early_return(self, mock_helpers):
        from agent.tools.update_booking import _update_booking_impl

        result = parse(
            await _update_booking_impl(
                services=["corte dama"],
                stylist_name="Marta Test",
                no_preference_stylist=False,
                date_iso=None,               # null — triggers "no date" block without fix
                date_text=None,
                audience=None,
                no_more_services=True,
                extras_asked=True,
                customer_full_name="Ana García",
                customer_known=True,
                notes_asked=True,
                slot_iso=FUTURE_ISO,         # fix derives date_iso from this
                recently_offered_slots=_make_offered_slots(),
                messages=[],
                policy_accepted=True,
            )
        )

        # After fix: date_iso derived (today+4) → bypasses offer_slots early return → pre-book gate.
        # Before fix (RED): date_iso=None → "no date" block fires → offer_slots.
        assert result["next_step"] == "pre_book_validation_required", (
            f"Expected pre_book_validation_required (date derived from slot_iso), "
            f"got: {result['next_step']!r}. Full payload: {result}"
        )


# ---------------------------------------------------------------------------
# Case 4 (GREEN from start): valid date_iso + malformed slot_iso → no derivation
# ---------------------------------------------------------------------------


class TestMalformedSlotNoDerivation:
    """Unparseable slot_iso leaves date_iso unchanged — _parse_iso_to_utc returns None."""

    @pytest.mark.asyncio
    async def test_malformed_slot_iso_preserves_original_date_iso(self, mock_helpers):
        from agent.tools.update_booking import _update_booking_impl

        result = parse(
            await _update_booking_impl(
                services=["corte dama"],
                stylist_name="Marta Test",
                no_preference_stylist=False,
                date_iso=FUTURE_DATE,              # valid future date
                date_text=None,
                audience=None,
                no_more_services=True,
                extras_asked=True,
                customer_full_name="Ana García",
                customer_known=True,
                notes_asked=True,
                slot_iso="not-a-valid-iso",        # malformed — _parse_iso_to_utc returns None
                recently_offered_slots=None,
                messages=[],
                policy_accepted=False,             # policy gate fires early for clean assertion
            )
        )

        # No derivation: _parse_iso_to_utc("not-a-valid-iso") → None → date_iso preserved.
        # Date validation passes (future date) → collected["date_iso"] = FUTURE_DATE.
        assert result["collected"]["date_iso"] == FUTURE_DATE, (
            f"date_iso should be preserved when slot_iso is malformed, got: {result}"
        )
        # Explicit terminal step: with a non-null slot_iso and policy_accepted=False, the
        # policy gate intercepts. Asserting the exact value (not an exclusion list) catches
        # a regression to any other branch, and proves G3 did NOT fire on the valid date.
        assert result["next_step"] == "policy_acceptance_required", (
            f"Expected policy_acceptance_required (G3 cleared, policy gate intercepts), "
            f"got: {result['next_step']!r}. Full payload: {result}"
        )


# ---------------------------------------------------------------------------
# Case 5 (RED → GREEN): no_preference_stylist=True + stale date_iso + valid slot_iso
# ---------------------------------------------------------------------------


class TestNoPreferenceStylistDateDerived:
    """The 'cualquier estilista' path must also derive date_iso from slot_iso.

    Plausible production scenario: customer says "any stylist", hits an advance-policy
    redirect, then picks a slot by number. The derivation runs after both stylist
    branches merge, so the no-preference path must behave identically to Case 1.
    """

    @pytest.mark.asyncio
    async def test_date_iso_derived_with_no_preference_stylist(self, mock_helpers):
        from agent.tools.update_booking import _update_booking_impl

        result = parse(
            await _update_booking_impl(
                services=["corte dama"],
                stylist_name=None,            # no explicit stylist
                no_preference_stylist=True,   # "cualquier estilista"
                date_iso=TODAY_ISO,           # stale — today → G3 fires without fix
                date_text=None,
                audience=None,
                no_more_services=True,
                extras_asked=True,
                customer_full_name="Ana García",
                customer_known=True,
                notes_asked=True,
                slot_iso=FUTURE_ISO,          # fix derives date_iso from here
                recently_offered_slots=_make_offered_slots(),
                messages=[],
                policy_accepted=True,
            )
        )

        # After fix: date_iso derived (today+4) → G3 clears on the no-preference path too.
        # Before fix (RED): validate_booking_date(today) fires G3 → advance_policy_violated.
        assert result["next_step"] == "pre_book_validation_required", (
            f"Expected pre_book_validation_required on the no_preference_stylist path, "
            f"got: {result['next_step']!r}. Full payload: {result}"
        )
