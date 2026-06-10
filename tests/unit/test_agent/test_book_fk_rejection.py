"""T12 — I1: Integration tests for FK validator wiring in book.py.

Spec: REQ-I1 / SC-I1-B, SC-I1-C

Verifies that when book() is called with an invalid service_id or stylist_id,
it returns a rejected ToolResponse with the correct next_step and no appointment
row is created. Uses mocking to avoid needing a live DB (consistent with the
existing test_book_tool.py pattern).

TDD: written before T13 wires the validator into book.py.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_fk_result(ok: bool, error_code: str | None, missing_ids: list, msg: str | None):
    """Build a FKValidationResult-like MagicMock."""
    r = MagicMock()
    r.ok = ok
    r.error_code = error_code
    r.missing_ids = missing_ids
    r.error_message = msg
    return r


@pytest.mark.asyncio
async def test_book_rejects_invalid_service_id() -> None:
    """SC-I1-B: book() with an invalid service_id returns rejected ToolResponse.

    - status must be 'rejected'
    - next_step must be 'invalid_service_ids'
    - payload must contain 'missing_service_ids'
    - No appointment row is created (session.add never called)
    """
    from agent.tools.book import book

    bad_svc_id = uuid4()
    stylist_uuid = uuid4()

    # FK validator: service check fails, stylist check not reached
    invalid_svc_result = _make_fk_result(
        ok=False,
        error_code="invalid_service_ids",
        missing_ids=[bad_svc_id],
        msg=f"service_id inválido: {bad_svc_id}. Vuelve a leer el <catalog>.",
    )

    # Duration query result (returns something so we can confirm it's NOT reached)
    mock_dur_rows = MagicMock()
    mock_dur_rows.fetchall.return_value = [(60,)]

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://example.com"

    with (
        patch("database.connection.get_async_session", return_value=mock_session),
        patch(
            "agent.tools.book.validate_service_ids_exist",
            new_callable=AsyncMock,
            return_value=invalid_svc_result,
        ),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch(
            "agent.tools.book.check_slot_availability",
            new_callable=AsyncMock,
            return_value={"available": True},
        ),
    ):
        result_json = await book.coroutine(
            service_ids=[str(bad_svc_id)],
            stylist_id=str(stylist_uuid),
            start_iso="2026-06-15T10:00:00+00:00",
            customer_full_name="Ana García",
            confirmed=True,
            pre_book_validated=True,
            state={"customer_phone": "+34999000001"},
        )

    result = json.loads(result_json)

    assert (
        result["status"] == "rejected"
    ), f"Expected status='rejected' for invalid service_id, got: {result}"
    assert (
        result.get("next_step") == "invalid_service_ids"
    ), f"Expected next_step='invalid_service_ids', got: {result.get('next_step')}"
    assert "missing_service_ids" in result.get(
        "payload", {}
    ), f"Expected 'missing_service_ids' in payload, got: {result.get('payload')}"
    # No appointment should have been inserted
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_book_rejects_invalid_stylist_id() -> None:
    """SC-I1-B variant: book() with an invalid stylist_id returns rejected ToolResponse.

    - status must be 'rejected'
    - next_step must be 'invalid_stylist_id'
    - No appointment row is created
    """
    from agent.tools.book import book

    svc_id = uuid4()
    bad_sty_id = uuid4()

    # FK validator: service check passes, stylist check fails
    valid_svc_result = _make_fk_result(ok=True, error_code=None, missing_ids=[], msg=None)
    invalid_sty_result = _make_fk_result(
        ok=False,
        error_code="invalid_stylist_id",
        missing_ids=[bad_sty_id],
        msg=f"stylist_id inválido: {bad_sty_id}.",
    )

    # Duration query result
    mock_dur_rows = MagicMock()
    mock_dur_rows.fetchall.return_value = [(60,)]

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_dur_rows)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://example.com"

    with (
        patch("database.connection.get_async_session", return_value=mock_session),
        patch(
            "agent.tools.book.validate_service_ids_exist",
            new_callable=AsyncMock,
            return_value=valid_svc_result,
        ),
        patch(
            "agent.tools.book.validate_stylist_id_exists",
            new_callable=AsyncMock,
            return_value=invalid_sty_result,
        ),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch(
            "agent.tools.book.check_slot_availability",
            new_callable=AsyncMock,
            return_value={"available": True},
        ),
    ):
        result_json = await book.coroutine(
            service_ids=[str(svc_id)],
            stylist_id=str(bad_sty_id),
            start_iso="2026-06-15T10:00:00+00:00",
            customer_full_name="Ana García",
            confirmed=True,
            pre_book_validated=True,
            state={"customer_phone": "+34999000001"},
        )

    result = json.loads(result_json)

    assert (
        result["status"] == "rejected"
    ), f"Expected status='rejected' for invalid stylist_id, got: {result}"
    assert (
        result.get("next_step") == "invalid_stylist_id"
    ), f"Expected next_step='invalid_stylist_id', got: {result.get('next_step')}"
    # No appointment should have been inserted
    mock_session.add.assert_not_called()
