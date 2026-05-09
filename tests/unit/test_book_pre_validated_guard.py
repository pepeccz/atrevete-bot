"""Unit tests for pre_book_validated guard in agent.tools.book.

R2.3: book() MUST refuse with status='rejected' + next_step='pre_book_validation_required'
when pre_book_validated=False, and MUST NOT write any DB row.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agent.tools.book import book


@pytest.mark.asyncio
async def test_book_rejected_when_pre_book_validated_false() -> None:
    """book(pre_book_validated=False) returns rejected with pre_book_validation_required."""
    result = await book.ainvoke(
        {
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "stylist_id": "00000000-0000-0000-0000-000000000002",
            "start_iso": "2026-05-10T10:00:00+00:00",
            "customer_phone": "+5491112345678",
            "customer_full_name": "Ana García",
            "confirmed": True,
            "pre_book_validated": False,
        }
    )
    payload = json.loads(result)
    assert payload["status"] == "rejected"
    assert payload["next_step"] == "pre_book_validation_required"


@pytest.mark.asyncio
async def test_book_rejected_pre_book_validated_false_no_db_write() -> None:
    """book(pre_book_validated=False) must NOT call BookingService (no DB access)."""
    with patch(
        "agent.tools.book.BookingService.create_appointment",
    ) as mock_service:
        result = await book.ainvoke(
            {
                "service_ids": ["00000000-0000-0000-0000-000000000001"],
                "stylist_id": "00000000-0000-0000-0000-000000000002",
                "start_iso": "2026-05-10T10:00:00+00:00",
                "customer_phone": "+5491112345678",
                "customer_full_name": "Ana García",
                "confirmed": True,
                "pre_book_validated": False,
            }
        )
    mock_service.assert_not_called()
    payload = json.loads(result)
    assert payload["status"] == "rejected"


@pytest.mark.asyncio
async def test_book_proceeds_when_pre_book_validated_true() -> None:
    """book(pre_book_validated=True, confirmed=True) passes the gate and hits DB logic."""
    # We only test that the gate is NOT triggered — DB errors expected (no real DB).
    result = await book.ainvoke(
        {
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "stylist_id": "00000000-0000-0000-0000-000000000002",
            "start_iso": "2026-05-10T10:00:00+00:00",
            "customer_phone": "+5491112345678",
            "customer_full_name": "Ana García",
            "confirmed": True,
            "pre_book_validated": True,
        }
    )
    payload = json.loads(result)
    # Gate passed — will fail at DB but NOT with pre_book_validation_required
    assert payload.get("next_step") != "pre_book_validation_required"


@pytest.mark.asyncio
async def test_book_pre_book_validated_default_is_false() -> None:
    """Omitting pre_book_validated defaults to False → rejected."""
    result = await book.ainvoke(
        {
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "stylist_id": "00000000-0000-0000-0000-000000000002",
            "start_iso": "2026-05-10T10:00:00+00:00",
            "customer_phone": "+5491112345678",
            "customer_full_name": "Ana García",
            "confirmed": True,
            # pre_book_validated omitted → should default False → rejected
        }
    )
    payload = json.loads(result)
    assert payload["status"] == "rejected"
    assert payload["next_step"] == "pre_book_validation_required"
