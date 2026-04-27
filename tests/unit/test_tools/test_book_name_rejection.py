"""Unit tests for book.py structured name rejection.

Tests SPEC-5.1→5.3, ADR-5. All tests are RED before T6 (replace ValueError path).
"""
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_book_rejects_single_token_name():
    """customer_full_name='Maite' → status=rejected, next_step=name_required."""
    from agent.tools.book import book

    raw = await book.ainvoke(
        {
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "stylist_id": "00000000-0000-0000-0000-000000000002",
            "start_iso": "2026-05-10T09:00:00+02:00",
            "customer_phone": "+34600000001",
            "customer_full_name": "Maite",
            "confirmed": True,
        }
    )
    data = json.loads(raw)
    assert data["status"] == "rejected"
    assert data["next_step"] == "name_required"


@pytest.mark.asyncio
async def test_book_rejects_empty_name():
    """customer_full_name='' → Guard 2 (incomplete_booking) or name_required — always rejected.

    Guard 2 (`if not customer_full_name`) fires before the name-validator for
    empty strings (falsy check). SPEC-5.3 only requires no DB write, which is
    satisfied regardless of which guard fires first.
    """
    from agent.tools.book import book

    raw = await book.ainvoke(
        {
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "stylist_id": "00000000-0000-0000-0000-000000000002",
            "start_iso": "2026-05-10T09:00:00+02:00",
            "customer_phone": "+34600000001",
            "customer_full_name": "",
            "confirmed": True,
        }
    )
    data = json.loads(raw)
    # Rejected before any DB write — SPEC-5.3 satisfied
    assert data["status"] == "rejected"


@pytest.mark.asyncio
async def test_book_rejects_whitespace_only_name():
    """customer_full_name='   ' → status=rejected, next_step=name_required.

    Whitespace-only passes Guard 2 (truthy string) but fails _validate_full_name.
    """
    from agent.tools.book import book

    raw = await book.ainvoke(
        {
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "stylist_id": "00000000-0000-0000-0000-000000000002",
            "start_iso": "2026-05-10T09:00:00+02:00",
            "customer_phone": "+34600000001",
            "customer_full_name": "   ",
            "confirmed": True,
        }
    )
    data = json.loads(raw)
    assert data["status"] == "rejected"
    assert data["next_step"] == "name_required"


@pytest.mark.asyncio
async def test_book_single_token_name_returns_name_required_message():
    """Rejection message explains what is missing (SPEC-5.2)."""
    from agent.tools.book import book

    raw = await book.ainvoke(
        {
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "stylist_id": "00000000-0000-0000-0000-000000000002",
            "start_iso": "2026-05-10T09:00:00+02:00",
            "customer_phone": "+34600000001",
            "customer_full_name": "Maite",
            "confirmed": True,
        }
    )
    data = json.loads(raw)
    assert data["status"] == "rejected"
    assert data["next_step"] == "name_required"
    # errors should describe the requirement
    assert data.get("errors"), "Expected non-empty errors list"
    errors_text = " ".join(data["errors"]).lower()
    assert "nombre" in errors_text or "apellido" in errors_text
