"""Tests for update_booking relative-date path via date_text parameter.

Covers spec scenarios B-14, B-15, B-16.

All resolver calls and datetime.now are mocked — no DB access required.

Post-PR#2: patches target BookingQueryService.resolve_all and
BookingQueryService.resolve_audience_variants instead of _booking_helpers.* functions.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def parse(raw: str) -> dict:
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

_TODAY_DATE = date.today()
_RESOLVED_DATE = _TODAY_DATE + timedelta(days=10)  # far enough to pass lead-time gate
_TODAY_DT = datetime.combine(_TODAY_DATE, datetime.min.time()).replace(tzinfo=timezone.utc)


@pytest.fixture
def mock_helpers():
    """Patch all DB helpers so update_booking runs without a real DB.

    Post-PR#2: patches BookingQueryService.resolve_all and resolve_audience_variants.
    """
    from agent.services.booking_query_service import ResolveAllResult

    resolve_all_result = ResolveAllResult(
        success=True,
        service_ids=["svc-uuid-001"],
        unknown_names=[],
        stylist_id="stylist-uuid-001",
        audience_variants=("none", "", []),
        categories=set(),
        id_to_category={},
        active_stylists=[],
        has_category_mix=False,
        hair_services=[],
        aesth_services=[],
        both_services=[],
        error_message=None,
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            new=AsyncMock(return_value=resolve_all_result),
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        # Patch is_date_closed so tests don't hit the DB and assume an open day.
        patch(
            "agent.tools._booking_validators.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        yield


class TestDateTextResolves:
    """Scenario B-14: date_text resolves and booking proceeds normally."""

    @pytest.mark.asyncio
    async def test_b14_date_text_resolves_and_books(self, mock_helpers):
        import json
        from unittest.mock import MagicMock

        slot_iso = f"{_RESOLVED_DATE.isoformat()}T10:00:00+02:00"

        avail_msg = MagicMock()
        avail_msg.name = "check_availability"
        avail_msg.content = json.dumps({
            "status": "ok",
            "payload": {
                "slots": [{"start_iso": slot_iso, "stylist_id": "stylist-uuid-001"}],
                "exact_match": True,
            },
        })

        with (
            # Patch at the module where the name is BOUND (module-level import in _booking_validators)
            patch(
                "agent.tools._booking_validators.resolve_relative_date",
                return_value=_RESOLVED_DATE,
            ),
            patch(
                "agent.tools.update_booking.datetime"
            ) as mock_dt,
        ):
            mock_dt.now.return_value = _TODAY_DT
            mock_dt.fromisoformat = datetime.fromisoformat  # keep real parsing

            from agent.tools.update_booking import _update_booking_impl

            result = parse(
                await _update_booking_impl(
                    services=["corte dama"],
                    stylist_name="Marta",
                    no_preference_stylist=False,
                    date_iso=None,
                    date_text="en diez días",
                    audience=None,
                    # New gates must be pre-satisfied so the test reaches date resolution
                    no_more_services=True,
                    extras_asked=True,
                    customer_full_name="Ana García",
                    customer_known=False,
                    notes_asked=True,
                    slot_iso=slot_iso,
                    messages=[avail_msg],
                )
            )

        assert result["status"] == "ok"
        assert result["collected"]["date_iso"] == _RESOLVED_DATE.isoformat()
        assert result["next_step"] == "booking_ready"


class TestDateTextAmbiguous:
    """Scenario B-15: ambiguous date_text → clarification, no exception."""

    @pytest.mark.asyncio
    async def test_b15_ambiguous_date_text_returns_clarification(self, mock_helpers):
        with (
            patch(
                "agent.tools._booking_validators.resolve_relative_date",
                return_value=None,
            ),
            patch(
                "agent.tools.update_booking.datetime"
            ) as mock_dt,
        ):
            mock_dt.now.return_value = _TODAY_DT
            mock_dt.fromisoformat = datetime.fromisoformat

            from agent.tools.update_booking import _update_booking_impl

            result = parse(
                await _update_booking_impl(
                    services=["corte dama"],
                    stylist_name="Marta",
                    no_preference_stylist=False,
                    date_iso=None,
                    date_text="la semana que viene",
                    audience=None,
                    no_more_services=True,
                    extras_asked=True,
                    customer_full_name="Ana García",
                    customer_known=False,
                    notes_asked=True,
                )
            )

        assert result["next_step"] == "date_clarification_required"
        assert result["errors"]  # at least one error message
        assert result["status"] in ("partial", "rejected")


class TestDateIsoPrecedence:
    """Scenario B-16: date_iso takes precedence over date_text."""

    @pytest.mark.asyncio
    async def test_b16_date_iso_wins_over_date_text(self, mock_helpers):
        import json
        from unittest.mock import MagicMock

        future_date_iso = _RESOLVED_DATE.isoformat()
        slot_iso = f"{future_date_iso}T10:00:00+02:00"

        avail_msg = MagicMock()
        avail_msg.name = "check_availability"
        avail_msg.content = json.dumps({
            "status": "ok",
            "payload": {
                "slots": [{"start_iso": slot_iso, "stylist_id": "stylist-uuid-001"}],
                "exact_match": True,
            },
        })

        with (
            patch(
                "agent.booking.resolvers.time_resolver.resolve_relative_date",
            ) as mock_resolve,
            patch(
                "agent.tools.update_booking.datetime"
            ) as mock_dt,
        ):
            mock_dt.now.return_value = _TODAY_DT
            mock_dt.fromisoformat = datetime.fromisoformat

            from agent.tools.update_booking import _update_booking_impl

            result = parse(
                await _update_booking_impl(
                    services=["corte dama"],
                    stylist_name="Marta",
                    no_preference_stylist=False,
                    date_iso=future_date_iso,
                    date_text="mañana",
                    audience=None,
                    no_more_services=True,
                    extras_asked=True,
                    customer_full_name="Ana García",
                    customer_known=False,
                    notes_asked=True,
                    slot_iso=slot_iso,
                    messages=[avail_msg],
                )
            )

        # date_iso takes precedence → resolver should NOT be called
        mock_resolve.assert_not_called()
        assert result["collected"]["date_iso"] == future_date_iso
        assert result["next_step"] == "booking_ready"
