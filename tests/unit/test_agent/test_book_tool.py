"""
Tests for agent/tools/book.py — Phase 4 TDD (calendar link).

T4.1 RED: _build_gcal_link formats URL correctly (pure function).
T4.3 RED: book() success path returns calendar_link in payload.

Post-PR4: patches BookingService.create_appointment, not DB sessions directly.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# T4.1 — _build_gcal_link pure function
# ---------------------------------------------------------------------------


def test_build_gcal_link_formats_url():
    """_build_gcal_link returns a well-formed Google Calendar deep-link."""
    from agent.tools.book import _build_gcal_link

    start = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 5, 1, 11, 0, 0, tzinfo=UTC)

    url = _build_gcal_link(
        start=start,
        end=end,
        service_names="Corte de Mujer",
        stylist_name="María",
        notes="Teñido previo",
    )

    # Must start with the correct base
    assert url.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE")

    # Must contain correctly formatted UTC dates
    assert "dates=20260501T100000Z/20260501T110000Z" in url

    # Title must be URL-encoded (spaces → %20)
    assert "Corte" in url  # at minimum the un-encoded part must appear
    assert "text=" in url

    # Details and location must be present
    assert "details=" in url
    assert "location=" in url


def test_build_gcal_link_encodes_special_chars():
    """_build_gcal_link percent-encodes service names and stylist names."""
    from agent.tools.book import _build_gcal_link

    start = datetime(2026, 6, 15, 14, 30, 0, tzinfo=UTC)
    end = datetime(2026, 6, 15, 16, 0, 0, tzinfo=UTC)

    url = _build_gcal_link(
        start=start,
        end=end,
        service_names="Corte & Peinado",
        stylist_name="José García",
        notes=None,
    )

    # Dates must be correct
    assert "dates=20260615T143000Z/20260615T160000Z" in url

    # Ampersand in service name must be encoded (not appear raw in the text= value)
    # The raw '&' between query params is fine; within the text value it must be encoded
    text_part = url.split("text=")[1].split("&")[0]
    assert "&" not in text_part  # raw & would break the URL


# ---------------------------------------------------------------------------
# T4.3 — book() success path returns calendar_link in payload
# (post-PR4: patches BookingService.create_appointment)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_returns_calendar_link_on_success():
    """Successful book() call must include calendar_link in the JSON payload.

    Post-PR4: patches BookingService.create_appointment — tool is a thin wrapper.
    """
    from agent.services.booking_service import BookingResult
    from agent.tools.book import book

    stylist_uuid = uuid4()
    service_uuid = uuid4()
    appointment_uuid = uuid4()
    customer_uuid = uuid4()
    start_time = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    end_time = start_time + timedelta(hours=1)

    mock_result = BookingResult(
        success=True,
        appointment_id=appointment_uuid,
        customer_id=customer_uuid,
        start_time=start_time,
        end_time=end_time,
        service_names="Corte de Mujer",
        stylist_display_name="María",
    )

    with patch(
        "agent.tools.book.BookingService.create_appointment",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await book.ainvoke(
            {
                "service_ids": [str(service_uuid)],
                "stylist_id": str(stylist_uuid),
                "start_iso": "2026-05-01T10:00:00+00:00",
                "customer_phone": "+5491112345678",
                "customer_full_name": "Ana García",
                "confirmed": True,
                "pre_book_validated": True,
                "notes": "Sin fragancia",
            }
        )

    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert "calendar_link" in payload["payload"]
    assert payload["payload"]["calendar_link"].startswith("https://calendar.google.com")
    assert payload["payload"]["appointment_id"] == str(appointment_uuid)
    assert payload["payload"]["customer_id"] == str(customer_uuid)
