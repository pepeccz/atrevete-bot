"""
Tests for agent/tools/book.py — Phase 4 TDD (calendar link).

T4.1 RED: _build_gcal_link formats URL correctly (pure function).
T4.3 RED: book() success path returns calendar_link in payload.
"""

import json
from datetime import UTC, datetime
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
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_returns_calendar_link_on_success():
    """Successful book() call must include calendar_link in the JSON payload."""
    from agent.tools.book import book

    stylist_uuid = uuid4()
    service_uuid = uuid4()
    appointment_uuid = uuid4()
    customer_uuid = uuid4()

    # --- Mock DB session (first session: transaction; second: service names; third: stylist) ---
    mock_service = MagicMock()
    mock_service.duration_minutes = 60
    mock_service.name = "Corte de Mujer"

    mock_customer = MagicMock()
    mock_customer.id = customer_uuid
    mock_customer.policy_accepted_at = datetime(2026, 1, 1, tzinfo=UTC)
    mock_customer.policy_version = "1.0"

    mock_stylist = MagicMock()
    mock_stylist.name = "María"

    # Session for the main transaction
    mock_txn_session = AsyncMock()
    mock_txn_session.execute = AsyncMock()
    mock_txn_session.get = AsyncMock(return_value=mock_stylist)
    mock_txn_session.flush = AsyncMock()
    mock_txn_session.commit = AsyncMock()
    mock_txn_session.add = MagicMock()
    mock_txn_session.__aenter__ = AsyncMock(return_value=mock_txn_session)
    mock_txn_session.__aexit__ = AsyncMock(return_value=False)

    # Duration query result
    mock_dur_rows = MagicMock()
    mock_dur_rows.fetchall = MagicMock(return_value=[(60,)])
    # Customer lookup — returns existing customer with policy already accepted
    mock_cust_rows = MagicMock()
    mock_cust_rows.scalar_one_or_none = MagicMock(return_value=mock_customer)
    # Stylist get (after commit)
    mock_sty_get_rows = MagicMock()

    call_count = [0]

    async def mock_execute(stmt):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_dur_rows
        if call_count[0] == 2:
            return mock_cust_rows
        return mock_sty_get_rows

    mock_txn_session.execute.side_effect = mock_execute

    # Session for GCal service name fetch
    mock_gcal_session = AsyncMock()
    mock_gcal_session.execute = AsyncMock()
    mock_gcal_session.__aenter__ = AsyncMock(return_value=mock_gcal_session)
    mock_gcal_session.__aexit__ = AsyncMock(return_value=False)

    svc_name_rows = MagicMock()
    svc_name_rows.fetchall = MagicMock(return_value=[("Corte de Mujer",)])
    mock_gcal_session.execute.return_value = svc_name_rows

    # Session for stylist name fetch (after commit)
    mock_sty_session = AsyncMock()
    mock_sty_session.get = AsyncMock(return_value=mock_stylist)
    mock_sty_session.__aenter__ = AsyncMock(return_value=mock_sty_session)
    mock_sty_session.__aexit__ = AsyncMock(return_value=False)

    session_call = [0]

    def make_session(*args, **kwargs):
        session_call[0] += 1
        if session_call[0] == 1:
            return mock_txn_session
        if session_call[0] == 2:
            return mock_gcal_session
        return mock_sty_session

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://example.com"

    ok_fk = MagicMock()
    ok_fk.ok = True
    ok_fk.missing_ids = []
    ok_fk.payload = {}

    with (
        patch("database.connection.get_async_session", side_effect=make_session),
        patch(
            "agent.services.gcal_push_service.fire_and_forget_push_appointment",
            new_callable=AsyncMock,
        ),
        patch("agent.tools.book.uuid4", return_value=appointment_uuid),
        patch(
            "agent.tools.book.check_slot_availability",
            new_callable=AsyncMock,
            return_value={"available": True},
        ),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book.validate_service_ids_exist", new=AsyncMock(return_value=ok_fk)),
        patch("agent.tools.book.validate_stylist_id_exists", new=AsyncMock(return_value=ok_fk)),
        patch("agent.tools.book.accept_policy", new=AsyncMock()),
    ):
        result = await book.coroutine(
            service_ids=[str(service_uuid)],
            stylist_id=str(stylist_uuid),
            start_iso="2026-05-01T10:00:00+00:00",
            customer_full_name="Ana García",
            confirmed=True,
            pre_book_validated=True,
            policy_accepted=True,
            notes="Sin fragancia",
            state={
                "customer_phone": "+5491112345678",
                "recently_offered_slots": [
                    {
                        "start_iso": "2026-05-01T10:00:00+00:00",
                        "stylist_id": str(stylist_uuid),
                        "expires_at": "2099-01-01T00:00:00+00:00",
                    }
                ],
            },
        )

    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert "calendar_link" in payload["payload"]
    assert payload["payload"]["calendar_link"].startswith("https://calendar.google.com")
