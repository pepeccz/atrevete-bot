"""Policy acceptance integration tests for book tool (T20-T21).

Tests cover:
- T20: book rolls back appointment INSERT when policy_service.accept_policy raises PolicyConsentError
- T21: book calls accept_policy when collected.policy_accepted=True and customer needs consent;
       does NOT call when policy already accepted at current version

All tests use mock sessions — no live DB required.

NOTE: Tests call the book function directly (not via book.ainvoke) to avoid
LangChain/LangGraph async tool wrapper overhead in unit tests.
Refs: Spec S-6, §6 / Design §4.1-4.2 / Tasks T20-T21
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_SERVICE_ID = uuid4()
FAKE_STYLIST_ID = uuid4()
CUSTOMER_PHONE = "+34611000099"
FUTURE_ISO = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT10:00:00+02:00")


def _base_book_kwargs(*, policy_accepted: bool = False):
    """Kwargs for calling book.coroutine directly (bypasses LangChain wrapper).

    customer_phone is passed via state (InjectedState) — not as an LLM arg.
    """
    return {
        "service_ids": [str(FAKE_SERVICE_ID)],
        "stylist_id": str(FAKE_STYLIST_ID),
        "start_iso": FUTURE_ISO,
        "customer_full_name": "Ana García",
        "confirmed": True,
        "pre_book_validated": True,
        "notes": None,
        "policy_accepted": policy_accepted,
        "state": {"customer_phone": CUSTOMER_PHONE},
    }


def _make_customer_mock(
    *,
    policy_accepted_at=None,
    policy_version=None,
    phone=CUSTOMER_PHONE,
):
    c = MagicMock()
    c.id = uuid4()
    c.phone = phone
    c.first_name = "Ana"
    c.last_name = "García"
    c.policy_accepted_at = policy_accepted_at
    c.policy_version = policy_version
    return c


def _make_session_ctx(customer=None, stylist=None, duration=30):
    """Build a mock session context where the main DB operations succeed."""
    session = AsyncMock()

    # _fetch_service_duration: execute returns rows with duration
    dur_result = MagicMock()
    dur_result.fetchall.return_value = [(duration,)]

    # _get_or_create_customer: execute returns the customer scalar
    cust_result = MagicMock()
    cust_result.scalar_one_or_none.return_value = customer

    # Sequence: first execute = fetch service duration, second = find customer
    # Additional execute calls for GCal post-commit (service names) also go here
    svc_names_result = MagicMock()
    svc_names_result.fetchall.return_value = [("Corte Dama",)]

    session.execute = AsyncMock(side_effect=[dur_result, cust_result, svc_names_result])
    # session.get: first call in policy block returns customer (fresh lookup)
    # subsequent calls may also return customer (for Stylist in post-commit)
    session.get = AsyncMock(return_value=customer)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


# ---------------------------------------------------------------------------
# T20 — rollback on PolicyConsentError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_rolls_back_on_policy_service_failure():
    """T20: accept_policy raises PolicyConsentError → appointment NOT inserted, both rolled back.

    When policy_service.accept_policy raises PolicyConsentError inside the
    existing async with get_async_session() block, SQLAlchemy rolls back the
    entire transaction: no Appointment row and no CustomerConsent row exist.

    We verify:
    1. session.add (for Appointment) is NOT called when accept_policy raises first.
    2. session.commit is NOT called.
    3. The returned ToolResponse has next_step="retry_later" (error path).

    Spec S-6 / Design §4.2
    """
    from agent.services.policy_service import PolicyConsentError
    from agent.tools.book import book

    customer = _make_customer_mock(policy_accepted_at=None, policy_version=None)
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book.check_slot_availability", AsyncMock(return_value={"available": True})),
        patch(
            "agent.tools.book.accept_policy",
            AsyncMock(side_effect=PolicyConsentError("DB write failed")),
        ),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        result_json = await book.coroutine(**_base_book_kwargs(policy_accepted=True))

    result = json.loads(result_json)
    # PolicyConsentError propagates through; outer except catches it → retry_later
    assert result["next_step"] == "retry_later", (
        f"Expected retry_later when accept_policy raises, got: {result}"
    )
    # session.commit must NOT have been called
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# T21 — accept_policy called when needed, skipped when not needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_calls_policy_service_when_accepted():
    """T21a: policy_accepted=True + customer needs consent → accept_policy called once.

    Spec §6 / Design §4.1
    """
    from agent.tools.book import book

    customer = _make_customer_mock(policy_accepted_at=None, policy_version=None)
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://atrevetepeluqueria.com/politica-privacidad/"

    accept_policy_mock = AsyncMock(return_value=MagicMock())

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book.check_slot_availability", AsyncMock(return_value={"available": True})),
        patch("agent.tools.book.accept_policy", accept_policy_mock),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book._invalidate_cached_customer", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        result_json = await book.coroutine(**_base_book_kwargs(policy_accepted=True))

    result = json.loads(result_json)
    # accept_policy must have been called once
    accept_policy_mock.assert_called_once()
    # call should include correct policy_version and accepted_via
    call_kwargs = accept_policy_mock.call_args[1]
    assert call_kwargs.get("policy_version") == "1.0", (
        f"Expected policy_version='1.0' in accept_policy call: {call_kwargs}"
    )
    assert call_kwargs.get("accepted_via") == "whatsapp", (
        f"Expected accepted_via='whatsapp' in accept_policy call: {call_kwargs}"
    )


@pytest.mark.asyncio
async def test_book_does_not_call_policy_service_when_already_accepted():
    """T21b: policy_accepted=True but customer already has current version → accept_policy NOT called.

    Idempotency: skip the write when customer.policy_version already matches settings.
    Spec §6 / Design §4.1
    """
    from agent.tools.book import book

    # Customer already accepted current version
    customer = _make_customer_mock(
        policy_accepted_at=datetime.now(UTC) - timedelta(days=5),
        policy_version="1.0",  # matches settings
    )
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://atrevetepeluqueria.com/politica-privacidad/"

    accept_policy_mock = AsyncMock(return_value=MagicMock())

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book.check_slot_availability", AsyncMock(return_value={"available": True})),
        patch("agent.tools.book.accept_policy", accept_policy_mock),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book._invalidate_cached_customer", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        result_json = await book.coroutine(**_base_book_kwargs(policy_accepted=True))

    # accept_policy must NOT be called — customer already has current version
    accept_policy_mock.assert_not_called()


@pytest.mark.asyncio
async def test_book_does_not_call_policy_service_when_not_accepted():
    """T21c: policy_accepted=False → accept_policy is NOT called regardless of customer state.

    Spec §6 / Design §4.1
    """
    from agent.tools.book import book

    customer = _make_customer_mock(policy_accepted_at=None, policy_version=None)
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"

    accept_policy_mock = AsyncMock(return_value=MagicMock())

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book.check_slot_availability", AsyncMock(return_value={"available": True})),
        patch("agent.tools.book.accept_policy", accept_policy_mock),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        result_json = await book.coroutine(**_base_book_kwargs(policy_accepted=False))

    # policy_accepted=False → accept_policy must NOT be called
    accept_policy_mock.assert_not_called()


# ---------------------------------------------------------------------------
# T12 — B4: Policy gate blocks book when policy not accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_rejects_when_policy_not_accepted():
    """B4: book rejects when customer has stale policy version and policy_accepted=False.

    Given customer.policy_version="0.9" (stale) and policy_accepted=False,
    book() must return rejected + next_step=policy_acceptance_required
    without creating an appointment.
    """
    from agent.tools.book import book

    # Customer with stale policy (version mismatch)
    customer = _make_customer_mock(
        policy_accepted_at=datetime.now(UTC) - timedelta(days=30),
        policy_version="0.9",  # stale — settings is "1.0"
    )
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://atrevetepeluqueria.com/politica-privacidad/"

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book.check_slot_availability", AsyncMock(return_value={"available": True})),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        # policy_accepted=False — customer hasn't consented in this call
        result_json = await book.coroutine(**_base_book_kwargs(policy_accepted=False))

    result = json.loads(result_json)
    assert result["status"] == "rejected", (
        f"Expected rejected when policy not accepted, got: {result}"
    )
    assert result.get("next_step") == "policy_acceptance_required", (
        f"Expected next_step=policy_acceptance_required, got: {result}"
    )
    # Appointment must NOT have been inserted
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_book_passes_when_policy_accepted():
    """B4: book proceeds when customer has current policy version.

    Given customer.policy_version="1.0" (current), policy_accepted=True,
    booking proceeds and appointment is created.
    """
    from agent.tools.book import book

    customer = _make_customer_mock(
        policy_accepted_at=datetime.now(UTC) - timedelta(days=1),
        policy_version="1.0",  # current
    )
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://atrevetepeluqueria.com/politica-privacidad/"

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch("agent.tools.book.check_slot_availability", AsyncMock(return_value={"available": True})),
        patch("agent.tools.book.accept_policy", AsyncMock(return_value=MagicMock())),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book._invalidate_cached_customer", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        result_json = await book.coroutine(**_base_book_kwargs(policy_accepted=True))

    result = json.loads(result_json)
    # Should NOT be rejected with policy_acceptance_required
    assert result.get("next_step") != "policy_acceptance_required", (
        f"Policy gate incorrectly fired for current version: {result}"
    )
