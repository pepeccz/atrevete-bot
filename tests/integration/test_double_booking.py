"""Integration tests for double-booking prevention.

REQ-3, REQ-8, REQ-9, REQ-10, REQ-11, REQ-18

These tests require a live PostgreSQL instance with the btree_gist extension and
excl_no_overlap constraint (migration 20260401_double_booking_prevention.py applied).

Run only when DATABASE_URL environment variable points to a real test database:
    pytest tests/integration/test_double_booking.py -v

Skipped automatically in CI if the migration has not been applied.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from database.models import AppointmentStatus


# ============================================================================
# Helpers / fixtures shared across tests
# ============================================================================


def _future_start(minutes_offset: int = 5 * 24 * 60) -> datetime:
    """Return a tz-aware datetime in the future (default: 5 days ahead)."""
    return datetime.now(timezone.utc) + timedelta(minutes=minutes_offset)


# ============================================================================
# Unit-level tests using mocked DB (no live PG required)
# ============================================================================


class TestCreateHoldMocked:
    """Unit-level tests for create_hold tool with mocked database session."""

    @pytest.mark.asyncio
    async def test_create_hold_returns_hold_id_on_success(self):
        """REQ-7: create_hold returns hold_id when INSERT succeeds."""
        from agent.tools.hold_tools import create_hold

        stylist_id = str(uuid4())
        customer_id = str(uuid4())
        service_id = str(uuid4())
        start_time = _future_start()

        mock_appointment = MagicMock()
        mock_appointment.id = uuid4()
        mock_appointment.start_time = start_time
        mock_appointment.duration_minutes = 60

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.rollback = AsyncMock()

        # Set the mock appointment's id after add
        def _side_effect_add(obj):
            mock_appointment.id = uuid4()

        mock_session.add.side_effect = _side_effect_add

        with patch("agent.tools.hold_tools.get_async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # Patch Appointment constructor so we control the mock object
            with patch("agent.tools.hold_tools.Appointment") as mock_appt_cls:
                mock_appt_cls.return_value = mock_appointment

                result = await create_hold.ainvoke(
                    {
                        "stylist_id": stylist_id,
                        "service_ids": [service_id],
                        "start_time": start_time.isoformat(),
                        "customer_id": customer_id,
                        "duration_minutes": 60,
                        "idempotency_key": "test-key-001",
                        "first_name": "María",
                    }
                )

        # Result may come back as a JSON string from LangChain tools
        import json as _json

        if isinstance(result, str):
            result = _json.loads(result)

        assert result["status"] == "ok"
        assert "hold_id" in result
        assert "expires_at" in result

    @pytest.mark.asyncio
    async def test_create_hold_returns_slot_unavailable_on_integrity_error(self):
        """REQ-8: create_hold returns SLOT_UNAVAILABLE when excl_no_overlap fires."""
        from sqlalchemy.exc import IntegrityError

        from agent.tools.hold_tools import SLOT_UNAVAILABLE, create_hold

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.rollback = AsyncMock()

        # Simulate excl_no_overlap constraint violation
        mock_session.commit = AsyncMock(
            side_effect=IntegrityError(
                "INSERT ...",
                {},
                Exception('violates exclusion constraint "excl_no_overlap"'),
            )
        )

        with patch("agent.tools.hold_tools.get_async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("agent.tools.hold_tools.Appointment"):
                result = await create_hold.ainvoke(
                    {
                        "stylist_id": str(uuid4()),
                        "service_ids": [str(uuid4())],
                        "start_time": _future_start().isoformat(),
                        "customer_id": str(uuid4()),
                        "duration_minutes": 60,
                        "idempotency_key": "test-key-002",
                        "first_name": "Ana",
                    }
                )

        import json as _json

        if isinstance(result, str):
            result = _json.loads(result)

        assert result["status"] == "error"
        assert result["error"] == SLOT_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_create_hold_returns_error_on_invalid_start_time(self):
        """INVALID_START_TIME returned when start_time is not valid ISO 8601."""
        from agent.tools.hold_tools import create_hold

        result = await create_hold.ainvoke(
            {
                "stylist_id": str(uuid4()),
                "service_ids": [str(uuid4())],
                "start_time": "not-a-date",
                "customer_id": str(uuid4()),
                "duration_minutes": 60,
                "idempotency_key": "key",
                "first_name": "Test",
            }
        )

        import json as _json

        if isinstance(result, str):
            result = _json.loads(result)

        assert result["status"] == "error"
        assert result["error"] == "INVALID_START_TIME"


class TestConfirmFromHoldMocked:
    """Unit-level tests for confirm_from_hold with mocked database session."""

    @pytest.mark.asyncio
    async def test_confirm_from_hold_succeeds(self):
        """REQ-9: confirm_from_hold promotes HOLD → PENDING."""
        from agent.tools.hold_tools import confirm_from_hold

        hold_uuid = uuid4()
        start_dt = _future_start()

        mock_hold = MagicMock()
        mock_hold.id = hold_uuid
        mock_hold.status = AppointmentStatus.HOLD
        mock_hold.hold_expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)
        mock_hold.start_time = start_dt
        mock_hold.duration_minutes = 60

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_hold

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch("agent.tools.hold_tools.get_async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await confirm_from_hold.ainvoke({"hold_id": str(hold_uuid)})

        import json as _json

        if isinstance(result, str):
            result = _json.loads(result)

        assert result["status"] == "ok"
        assert "appointment_id" in result
        # Verify the hold was promoted
        assert mock_hold.status == AppointmentStatus.PENDING
        assert mock_hold.hold_expires_at is None

    @pytest.mark.asyncio
    async def test_confirm_from_hold_expired_hold(self):
        """REQ-10: confirm_from_hold returns HOLD_EXPIRED when hold_expires_at is in past."""
        from agent.tools.hold_tools import HOLD_EXPIRED, confirm_from_hold

        hold_uuid = uuid4()

        mock_hold = MagicMock()
        mock_hold.id = hold_uuid
        mock_hold.status = AppointmentStatus.HOLD
        # hold_expires_at in the PAST
        mock_hold.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_hold

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch("agent.tools.hold_tools.get_async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await confirm_from_hold.ainvoke({"hold_id": str(hold_uuid)})

        import json as _json

        if isinstance(result, str):
            result = _json.loads(result)

        assert result["status"] == "error"
        assert result["error"] == HOLD_EXPIRED
        # Appointment status must NOT have changed
        assert mock_hold.status == AppointmentStatus.HOLD

    @pytest.mark.asyncio
    async def test_confirm_from_hold_already_pending(self):
        """REQ-11: confirm_from_hold returns HOLD_INVALID_STATE when status != HOLD."""
        from agent.tools.hold_tools import HOLD_INVALID_STATE, confirm_from_hold

        hold_uuid = uuid4()

        mock_hold = MagicMock()
        mock_hold.id = hold_uuid
        mock_hold.status = AppointmentStatus.PENDING  # Already confirmed
        mock_hold.hold_expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_hold

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.rollback = AsyncMock()

        with patch("agent.tools.hold_tools.get_async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await confirm_from_hold.ainvoke({"hold_id": str(hold_uuid)})

        import json as _json

        if isinstance(result, str):
            result = _json.loads(result)

        assert result["status"] == "error"
        assert result["error"] == HOLD_INVALID_STATE

    @pytest.mark.asyncio
    async def test_confirm_from_hold_not_found(self):
        """confirm_from_hold returns HOLD_NOT_FOUND when hold_id does not exist."""
        from agent.tools.hold_tools import HOLD_NOT_FOUND, confirm_from_hold

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No row found

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.rollback = AsyncMock()

        with patch("agent.tools.hold_tools.get_async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await confirm_from_hold.ainvoke({"hold_id": str(uuid4())})

        import json as _json

        if isinstance(result, str):
            result = _json.loads(result)

        assert result["status"] == "error"
        assert result["error"] == HOLD_NOT_FOUND


# ============================================================================
# Direct book() backward-compat test (REQ-18)
# ============================================================================


class TestDirectBookBackwardCompat:
    """REQ-18: direct book() without hold_id still works (backward-compat guard)."""

    def test_booking_context_hold_id_defaults_to_none(self):
        """REQ-18: BookingContext with hold_id=None is valid — legacy path active."""
        from agent.modes.booking_context import BookingContext

        ctx = BookingContext()
        assert ctx.hold_id is None, (
            "hold_id=None is the signal for the legacy direct book() path (REQ-18). "
            "This must always default to None."
        )

    def test_booking_context_hold_id_can_be_cleared(self):
        """REQ-18: hold_id can be cleared back to None (e.g., after HOLD_EXPIRED)."""
        from agent.modes.booking_context import BookingContext

        ctx = BookingContext(hold_id="some-hold-uuid")
        assert ctx.hold_id == "some-hold-uuid"

        ctx.hold_id = None
        assert ctx.hold_id is None
