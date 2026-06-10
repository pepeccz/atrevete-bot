"""Tests for Change J3: slot binding in book.py.

Change J: hallucination-tolerant-architecture-bundle. REQ-J3.

Tests written BEFORE implementation (TDD RED phase).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

SERVICE_ID = str(uuid4())
STYLIST_ID = str(uuid4())
SLOT_ISO = "2026-07-15T10:00:00+00:00"
CUSTOMER_PHONE = "+34999000001"
CUSTOMER_NAME = "María García"


def _make_offered_slot(start_iso: str, stylist_id: str | None = None) -> dict:
    return {
        "start_iso": start_iso,
        "stylist_id": stylist_id,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=14)).isoformat(),
        "turn_index": 0,
    }


# ---------------------------------------------------------------------------
# T7: book rejects slot not in recently_offered_slots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_slot_not_in_offered_rejects():
    """start_iso not in recently_offered_slots → error, no appointment created.

    FK guards pass (mocked), slot-bind guard fires and rejects before any DB write.
    Ordering: FK guards (J1) run first → slot-bind guard (J3) runs second.
    """
    from agent.tools.book import book

    state = {
        "customer_phone": CUSTOMER_PHONE,
        "recently_offered_slots": [_make_offered_slot("2026-07-15T11:00:00+00:00")],
    }

    ok_fk = MagicMock()
    ok_fk.ok = True
    ok_fk.missing_ids = []
    ok_fk.error_message = None

    mock_session = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("database.connection.get_async_session", return_value=mock_ctx),
        patch(
            "agent.tools.book.validate_service_ids_exist",
            new_callable=AsyncMock,
            return_value=ok_fk,
        ),
        patch(
            "agent.tools.book.validate_stylist_id_exists",
            new_callable=AsyncMock,
            return_value=ok_fk,
        ),
        patch(
            "agent.tools.book.validate_slot_in_offered",
            return_value=MagicMock(
                ok=False,
                error_code="slot_not_offered",
                error_message="El hueco no está entre los huecos ofrecidos.",
            ),
        ),
    ):
        result_json = await book.coroutine(
            service_ids=[SERVICE_ID],
            stylist_id=STYLIST_ID,
            start_iso=SLOT_ISO,
            customer_full_name=CUSTOMER_NAME,
            confirmed=True,
            pre_book_validated=True,
            state=state,
        )

    result = json.loads(result_json)
    assert (
        result["status"] == "rejected"
    ), f"Expected rejected for slot not in offered, got: {result['status']}"
    next_step = result.get("next_step", "")
    assert (
        "reoffer" in next_step or "slot" in next_step or "availability" in next_step
    ), f"Expected reoffer_slots or similar next_step, got: {next_step}"
    # Appointment must NOT have been added
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_book_empty_recently_offered_slots_rejects():
    """Empty recently_offered_slots → error with check_availability instruction."""
    from agent.tools.book import book

    state = {
        "customer_phone": CUSTOMER_PHONE,
        "recently_offered_slots": [],
    }

    ok_fk = MagicMock()
    ok_fk.ok = True
    ok_fk.missing_ids = []
    ok_fk.error_message = None

    mock_session = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("database.connection.get_async_session", return_value=mock_ctx),
        patch(
            "agent.tools.book.validate_service_ids_exist",
            new_callable=AsyncMock,
            return_value=ok_fk,
        ),
        patch(
            "agent.tools.book.validate_stylist_id_exists",
            new_callable=AsyncMock,
            return_value=ok_fk,
        ),
        patch(
            "agent.tools.book.validate_slot_in_offered",
            return_value=MagicMock(
                ok=False,
                error_code="slot_not_offered",
                error_message="No hay huecos ofrecidos. Llama a check_availability primero.",
            ),
        ),
    ):
        result_json = await book.coroutine(
            service_ids=[SERVICE_ID],
            stylist_id=STYLIST_ID,
            start_iso=SLOT_ISO,
            customer_full_name=CUSTOMER_NAME,
            confirmed=True,
            pre_book_validated=True,
            state=state,
        )

    result = json.loads(result_json)
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_book_no_recently_offered_slots_key_rejects():
    """Absent recently_offered_slots in state → error (fail-closed)."""
    from agent.tools.book import book

    state = {
        "customer_phone": CUSTOMER_PHONE,
        # recently_offered_slots absent from state
    }

    ok_fk = MagicMock()
    ok_fk.ok = True
    ok_fk.missing_ids = []
    ok_fk.error_message = None

    mock_session = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("database.connection.get_async_session", return_value=mock_ctx),
        patch(
            "agent.tools.book.validate_service_ids_exist",
            new_callable=AsyncMock,
            return_value=ok_fk,
        ),
        patch(
            "agent.tools.book.validate_stylist_id_exists",
            new_callable=AsyncMock,
            return_value=ok_fk,
        ),
        patch(
            "agent.tools.book.validate_slot_in_offered",
            return_value=MagicMock(
                ok=False,
                error_code="slot_not_offered",
                error_message="No hay huecos ofrecidos. Llama a check_availability primero.",
            ),
        ),
    ):
        result_json = await book.coroutine(
            service_ids=[SERVICE_ID],
            stylist_id=STYLIST_ID,
            start_iso=SLOT_ISO,
            customer_full_name=CUSTOMER_NAME,
            confirmed=True,
            pre_book_validated=True,
            state=state,
        )

    result = json.loads(result_json)
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_book_valid_slot_proceeds_past_binding_check():
    """Slot in recently_offered_slots passes binding check and proceeds to DB checks."""
    from agent.tools.book import book

    state = {
        "customer_phone": CUSTOMER_PHONE,
        "recently_offered_slots": [_make_offered_slot(SLOT_ISO, STYLIST_ID)],
    }

    with (
        patch(
            "agent.tools.book.validate_slot_in_offered",
            return_value=MagicMock(ok=True, error_code=None),
        ),
        # Also mock the downstream validators so we don't need a DB
        patch(
            "agent.tools.book.validate_service_ids_exist",
            new=AsyncMock(return_value=MagicMock(ok=True)),
        ),
        patch(
            "agent.tools.book.validate_stylist_id_exists",
            new=AsyncMock(return_value=MagicMock(ok=True)),
        ),
        patch(
            "agent.tools.book.check_slot_availability",
            new=AsyncMock(return_value=MagicMock(available=True)),
        ),
        patch("database.connection.get_async_session") as mock_ctx,
    ):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result_json = await book.coroutine(
            service_ids=[SERVICE_ID],
            stylist_id=STYLIST_ID,
            start_iso=SLOT_ISO,
            customer_full_name=CUSTOMER_NAME,
            confirmed=True,
            pre_book_validated=True,
            state=state,
        )

    result = json.loads(result_json)
    # Must NOT be rejected due to slot binding — may fail further down but not at slot check
    assert (
        result.get("next_step") != "reoffer_slots"
    ), f"Expected to pass slot binding check, got reoffer_slots: {result}"


def test_book_module_imports_validate_slot_in_offered():
    """validate_slot_in_offered must be callable from within book.py (module-level import)."""
    import importlib

    book_mod = importlib.import_module("agent.tools.book")

    # The module dict should have validate_slot_in_offered
    assert (
        "validate_slot_in_offered" in book_mod.__dict__
    ), "validate_slot_in_offered must be imported in agent/tools/book.py module namespace"
