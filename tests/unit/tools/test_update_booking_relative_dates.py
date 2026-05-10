"""Tests for update_booking relative-date path via date_text parameter.

Covers spec scenarios B-14, B-15, B-16.

All resolver calls and datetime.now are mocked — no DB access required.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def parse(raw: str) -> dict:
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

_TODAY_DATE = date(2026, 4, 27)
_TODAY_DT = datetime(2026, 4, 27, 10, 0, 0, tzinfo=timezone.utc)


def _mock_session_ctx(session_mock):
    """Return an async context manager that yields session_mock."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_session_with_service(service_id="svc-uuid-001", service_name="corte dama"):
    """Return a session mock that resolves the given service and has no audience variants."""
    session = AsyncMock()
    return session


@pytest.fixture
def mock_helpers():
    """Patch all DB helpers so update_booking runs without a real DB."""
    from database.models import ServiceCategory

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["svc-uuid-001"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            new=AsyncMock(return_value=(["svc-uuid-001"], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),  # no ambiguity → no disambiguation
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(return_value={ServiceCategory.HAIRDRESSING}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            new=AsyncMock(return_value="stylist-uuid-001"),
        ),
        patch(
            "database.connection.get_async_session",
        ) as mock_get_session,
        # Patch is_date_closed so tests don't hit the DB and assume an open day.
        patch(
            "shared.business_hours_validator.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        session_mock = AsyncMock()
        mock_get_session.return_value = _mock_session_ctx(session_mock)
        yield


class TestDateTextResolves:
    """Scenario B-14: date_text resolves and booking proceeds normally."""

    @pytest.mark.asyncio
    async def test_b14_date_text_resolves_and_books(self, mock_helpers):
        with (
            patch(
                "agent.booking.resolvers.time_resolver.resolve_relative_date",
                # Use today+3 (2026-04-30) so the new lead-time gate passes (MIN_BOOKING_DAYS=3).
                return_value=date(2026, 4, 30),
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
                    date_text="en tres días",
                    audience=None,
                    # New gates must be pre-satisfied so the test reaches date resolution
                    no_more_services=True,
                    extras_asked=True,
                    customer_full_name="Ana García",
                    customer_known=False,
                    notes_asked=True,
                )
            )

        assert result["status"] == "ok"
        assert result["collected"]["date_iso"] == "2026-04-30"
        assert result["next_step"] == "booking_ready"


class TestDateTextAmbiguous:
    """Scenario B-15: ambiguous date_text → clarification, no exception."""

    @pytest.mark.asyncio
    async def test_b15_ambiguous_date_text_returns_clarification(self, mock_helpers):
        with (
            patch(
                "agent.booking.resolvers.time_resolver.resolve_relative_date",
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
                    date_iso="2026-05-01",
                    date_text="mañana",
                    audience=None,
                    no_more_services=True,
                    extras_asked=True,
                    customer_full_name="Ana García",
                    customer_known=False,
                    notes_asked=True,
                )
            )

        # date_iso takes precedence → resolver should NOT be called
        mock_resolve.assert_not_called()
        assert result["collected"]["date_iso"] == "2026-05-01"
        assert result["next_step"] == "booking_ready"
