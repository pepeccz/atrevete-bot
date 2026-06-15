"""TDD tests: B1 IDOR fix — book tool must read customer_phone from InjectedState.

T2 (RED): Write failing tests that confirm:
  - book uses state['customer_phone'], not an LLM-supplied arg
  - book rejects when state['customer_phone'] is missing
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

FAKE_SERVICE_ID = str(uuid4())
FAKE_STYLIST_ID = str(uuid4())
STATE_PHONE = "+34611000001"
OTHER_PHONE = "+34611000002"
FUTURE_ISO = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT10:00:00+02:00")


def _make_customer_mock(phone=STATE_PHONE):
    c = MagicMock()
    c.id = uuid4()
    c.phone = phone
    c.first_name = "Ana"
    c.last_name = "García"
    c.policy_accepted_at = datetime.now(UTC) - timedelta(days=1)
    c.policy_version = "1.0"
    return c


def _make_session_ctx(customer=None, duration=30):
    """Mock session context for DB operations."""
    session = AsyncMock()
    dur_result = MagicMock()
    dur_result.fetchall.return_value = [(duration,)]
    cust_result = MagicMock()
    cust_result.scalar_one_or_none.return_value = customer
    svc_names_result = MagicMock()
    svc_names_result.fetchall.return_value = [("Corte Dama",)]
    session.execute = AsyncMock(side_effect=[dur_result, cust_result, svc_names_result])
    session.get = AsyncMock(return_value=customer)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


@pytest.mark.asyncio
async def test_book_uses_state_customer_phone():
    """B1: book reads customer_phone from InjectedState, not from LLM-supplied arg.

    When state['customer_phone'] = STATE_PHONE and no customer_phone kwarg is supplied,
    the booking must be created for STATE_PHONE.
    """
    from agent.tools.book import book

    customer = _make_customer_mock(phone=STATE_PHONE)
    ctx, session = _make_session_ctx(customer=customer)
    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://example.com"

    captured_phone = {}

    async def fake_get_or_create(sess, phone, first_name, last_name):
        captured_phone["phone"] = phone
        return customer

    ok_fk = MagicMock()
    ok_fk.ok = True
    ok_fk.missing_ids = []
    ok_fk.payload = {}

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book._get_or_create_customer", side_effect=fake_get_or_create),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book._invalidate_cached_customer", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
        patch("agent.tools.book.check_slot_availability", AsyncMock(return_value={"available": True})),
        patch("agent.tools.book.validate_service_ids_exist", AsyncMock(return_value=ok_fk)),
        patch("agent.tools.book.validate_stylist_id_exists", AsyncMock(return_value=ok_fk)),
        patch("agent.tools.book.accept_policy", AsyncMock()),
    ):
        # Call via coroutine — state kwarg provides the phone (InjectedState)
        result_json = await book.coroutine(
            service_ids=[FAKE_SERVICE_ID],
            stylist_id=FAKE_STYLIST_ID,
            start_iso=FUTURE_ISO,
            customer_full_name="Ana García",
            confirmed=True,
            pre_book_validated=True,
            policy_accepted=True,
            state={
                "customer_phone": STATE_PHONE,
                "recently_offered_slots": [
                    {
                        "start_iso": FUTURE_ISO,
                        "stylist_id": FAKE_STYLIST_ID,
                        "expires_at": "2099-01-01T00:00:00+00:00",
                    }
                ],
            },
        )

    result = json.loads(result_json)
    assert result["status"] == "ok", f"Expected ok, got: {result}"
    assert captured_phone.get("phone") == STATE_PHONE, (
        f"Expected booking for state phone {STATE_PHONE}, got {captured_phone.get('phone')}"
    )


@pytest.mark.asyncio
async def test_book_rejects_when_state_customer_phone_missing():
    """B1: book rejects with status='rejected' when state['customer_phone'] is absent."""
    from agent.tools.book import book

    result_json = await book.coroutine(
        service_ids=[FAKE_SERVICE_ID],
        stylist_id=FAKE_STYLIST_ID,
        start_iso=FUTURE_ISO,
        customer_full_name="Ana García",
        confirmed=True,
        pre_book_validated=True,
        state={},  # no customer_phone
    )

    result = json.loads(result_json)
    assert result["status"] == "rejected", f"Expected rejected, got: {result}"
    assert "incompleto" in str(result).lower() or "missing" in str(result).lower() or result.get("errors"), (
        f"Expected an error message indicating missing state, got: {result}"
    )
