"""Change L (L2) — policy re-ask loop regression tests.

QA V4 evidence (run 20260609_183226, impaciente-multiples-mensajes turn 11):
the customer accepted the policy, `update_booking(policy_accepted=True)` cleared
the gate, but the follow-up tool call dropped the `policy_accepted` round-trip
flag, so the gate re-fired and the bot re-asked for acceptance.

Root cause: acceptance was durable ONLY at `book(policy_accepted=True)` time.
Between the gate clear and `book`, the acceptance existed solely as an
LLM-controlled round-trip flag — one dropped flag re-fires the gate because the
DB has no consent row yet (brand-new customers have no `customers` row at all
until `book` creates it).

Fix under test (two durable layers, both written at gate-clear time):
1. DB truth — when `customer_id` is known, `accept_policy` persists
   `customers.policy_accepted_at` + a `customer_consents` row immediately.
2. Conversation marker — Redis key `policy_accepted:v2:{conversation_id}`
   covers brand-new customers without a DB row. Both gates (update_booking
   step 6c and book B4) consult the marker when the LLM flag is missing.

All tests use mocked sessions/Redis — no live DB or Redis required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tests.unit.test_update_booking_policy_gate import (
    FUTURE_DATE,
    FUTURE_SLOT_ISO,
    _make_check_avail_message,
    _make_customer_state,
    _make_settings_mock,
    _standard_patches,
)

CONVERSATION_ID = "qa-conv-l2-regression"


def parse_response(raw: str) -> dict:
    return json.loads(raw)


def _gate_kwargs(**overrides) -> dict:
    """Baseline kwargs that drive _update_booking_impl up to the policy gate."""
    stylist_id = overrides.pop("stylist_id", uuid4())
    base = {
        "services": ["corte"],
        "stylist_name": "Marta",
        "no_preference_stylist": False,
        "date_iso": FUTURE_DATE,
        "audience": None,
        "customer_full_name": "Juan García",
        "notes": None,
        "no_more_services": True,
        "extras_asked": True,
        "notes_asked": True,
        "customer_known": True,
        "slot_iso": FUTURE_SLOT_ISO,
        "variant_resolved": False,
        "pre_resolved_service_ids": None,
        "messages": [_make_check_avail_message(FUTURE_SLOT_ISO, str(stylist_id))],
        "policy_accepted": False,
        "policy_rejection_count": 0,
        "customer_id": str(uuid4()),
        "conversation_id": CONVERSATION_ID,
    }
    base.update(overrides)
    return base, stylist_id


# ---------------------------------------------------------------------------
# update_booking gate — marker recovery when the LLM drops the flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_booking_gate_recovers_from_marker_when_flag_dropped():
    """L2: gate must NOT re-fire when the conversation marker records acceptance.

    Customer needs policy (policy_accepted_at=None), the LLM dropped the
    round-trip flag (policy_accepted=False), but the Redis marker for this
    conversation holds the current POLICY_VERSION → gate clears.
    """
    from agent.tools.update_booking import _update_booking_impl

    kwargs, stylist_id = _gate_kwargs(policy_accepted=False)
    customer_state = _make_customer_state(policy_accepted_at=None, policy_version=None)
    settings = _make_settings_mock()

    with (
        _standard_patches(
            stylist_id=stylist_id,
            settings_mock=settings,
            customer_state_in_db=customer_state,
        ),
        patch(
            "agent.tools.update_booking.get_conversation_policy_acceptance",
            AsyncMock(return_value="1.0"),
        ),
        patch(
            "agent.tools.update_booking.set_conversation_policy_acceptance",
            AsyncMock(),
        ),
        patch("agent.tools.update_booking.accept_policy", AsyncMock(return_value=MagicMock())),
    ):
        result = parse_response(await _update_booking_impl(**kwargs))

    assert (
        result["next_step"] != "policy_acceptance_required"
    ), f"Gate re-fired despite conversation acceptance marker (re-ask loop!): {result}"
    collected = result.get("collected", {})
    assert (
        collected.get("policy_accepted") is True
    ), f"collected.policy_accepted must be True after marker recovery: {collected}"


@pytest.mark.asyncio
async def test_update_booking_gate_still_fires_without_flag_or_marker():
    """L2 (triangulation): no flag AND no marker → gate fires exactly as before."""
    from agent.tools.update_booking import _update_booking_impl

    kwargs, stylist_id = _gate_kwargs(policy_accepted=False)
    customer_state = _make_customer_state(policy_accepted_at=None, policy_version=None)
    settings = _make_settings_mock()

    with (
        _standard_patches(
            stylist_id=stylist_id,
            settings_mock=settings,
            customer_state_in_db=customer_state,
        ),
        patch(
            "agent.tools.update_booking.get_conversation_policy_acceptance",
            AsyncMock(return_value=None),
        ),
    ):
        result = parse_response(await _update_booking_impl(**kwargs))

    assert (
        result["next_step"] == "policy_acceptance_required"
    ), f"Gate must still fire when neither flag nor marker exists: {result}"


@pytest.mark.asyncio
async def test_update_booking_gate_ignores_marker_for_stale_version():
    """L2 (triangulation): a marker for an OLD policy version must NOT clear the gate."""
    from agent.tools.update_booking import _update_booking_impl

    kwargs, stylist_id = _gate_kwargs(policy_accepted=False)
    customer_state = _make_customer_state(policy_accepted_at=None, policy_version=None)
    settings = _make_settings_mock()  # POLICY_VERSION = "1.0"

    with (
        _standard_patches(
            stylist_id=stylist_id,
            settings_mock=settings,
            customer_state_in_db=customer_state,
        ),
        patch(
            "agent.tools.update_booking.get_conversation_policy_acceptance",
            AsyncMock(return_value="0.9"),
        ),
    ):
        result = parse_response(await _update_booking_impl(**kwargs))

    assert (
        result["next_step"] == "policy_acceptance_required"
    ), f"Stale-version marker must not clear the gate: {result}"


# ---------------------------------------------------------------------------
# update_booking gate — durable persistence at gate-clear time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_booking_persists_acceptance_on_gate_clear():
    """L2: clearing the gate with policy_accepted=True must persist acceptance durably.

    Both layers must be written: accept_policy (DB truth — customer_id known)
    and the conversation marker (covers later turns even if the DB write lands
    after the LLM's next tool call).
    """
    from agent.tools.update_booking import _update_booking_impl

    kwargs, stylist_id = _gate_kwargs(policy_accepted=True)
    customer_state = _make_customer_state(policy_accepted_at=None, policy_version=None)
    settings = _make_settings_mock()

    accept_policy_mock = AsyncMock(return_value=MagicMock())
    set_marker_mock = AsyncMock()

    with (
        _standard_patches(
            stylist_id=stylist_id,
            settings_mock=settings,
            customer_state_in_db=customer_state,
        ) as session,
        patch("agent.tools.update_booking.accept_policy", accept_policy_mock),
        patch(
            "agent.tools.update_booking.set_conversation_policy_acceptance",
            set_marker_mock,
        ),
    ):
        session.commit = AsyncMock()
        result = parse_response(await _update_booking_impl(**kwargs))

    assert result["next_step"] != "policy_acceptance_required", f"Gate must clear: {result}"
    accept_policy_mock.assert_called_once()
    call_kwargs = accept_policy_mock.call_args[1]
    assert call_kwargs.get("policy_version") == "1.0"
    assert call_kwargs.get("accepted_via") == "whatsapp"
    session.commit.assert_called()
    set_marker_mock.assert_called_once_with(CONVERSATION_ID, "1.0")


@pytest.mark.asyncio
async def test_update_booking_marker_set_even_without_customer_id():
    """L2: brand-new customer (no customers row, no customer_id) → marker still written.

    This is the exact QA V4 shape: the customer row does not exist until book()
    creates it, so the marker is the ONLY durable acceptance layer.
    """
    from agent.tools.update_booking import _update_booking_impl

    kwargs, stylist_id = _gate_kwargs(policy_accepted=True, customer_id=None)
    settings = _make_settings_mock()

    accept_policy_mock = AsyncMock(return_value=MagicMock())
    set_marker_mock = AsyncMock()

    with (
        _standard_patches(stylist_id=stylist_id, settings_mock=settings),
        patch("agent.tools.update_booking.accept_policy", accept_policy_mock),
        patch(
            "agent.tools.update_booking.set_conversation_policy_acceptance",
            set_marker_mock,
        ),
    ):
        result = parse_response(await _update_booking_impl(**kwargs))

    assert result["next_step"] != "policy_acceptance_required", f"Gate must clear: {result}"
    # No customer row → no DB write possible, but the marker MUST be set
    accept_policy_mock.assert_not_called()
    set_marker_mock.assert_called_once_with(CONVERSATION_ID, "1.0")


@pytest.mark.asyncio
async def test_update_booking_no_persistence_when_gate_not_needed():
    """L2 (triangulation): customer already accepted current version → no writes."""
    from datetime import UTC, datetime, timedelta

    from agent.tools.update_booking import _update_booking_impl

    kwargs, stylist_id = _gate_kwargs(policy_accepted=False)
    customer_state = _make_customer_state(
        policy_accepted_at=datetime.now(UTC) - timedelta(days=5),
        policy_version="1.0",
    )
    settings = _make_settings_mock()

    accept_policy_mock = AsyncMock(return_value=MagicMock())
    set_marker_mock = AsyncMock()
    get_marker_mock = AsyncMock(return_value=None)

    with (
        _standard_patches(
            stylist_id=stylist_id,
            settings_mock=settings,
            customer_state_in_db=customer_state,
        ),
        patch("agent.tools.update_booking.accept_policy", accept_policy_mock),
        patch(
            "agent.tools.update_booking.set_conversation_policy_acceptance",
            set_marker_mock,
        ),
        patch(
            "agent.tools.update_booking.get_conversation_policy_acceptance",
            get_marker_mock,
        ),
    ):
        result = parse_response(await _update_booking_impl(**kwargs))

    assert result["next_step"] == "booking_ready", f"Expected booking_ready: {result}"
    accept_policy_mock.assert_not_called()
    set_marker_mock.assert_not_called()
    # Marker lookup is only needed when the gate would otherwise fire
    get_marker_mock.assert_not_called()


# ---------------------------------------------------------------------------
# book gate (B4) — marker recovery when the LLM drops the flag between tools
# ---------------------------------------------------------------------------

from tests.unit.test_book_policy_integration import (  # noqa: E402
    _base_book_kwargs,
    _fk_guards_ok,
    _make_customer_mock,
    _make_session_ctx,
)


def _book_kwargs_with_conversation(*, policy_accepted: bool) -> dict:
    kwargs = _base_book_kwargs(policy_accepted=policy_accepted)
    kwargs["state"] = {**kwargs["state"], "conversation_id": CONVERSATION_ID}
    return kwargs


@pytest.mark.asyncio
async def test_book_gate_recovers_from_marker_when_flag_dropped():
    """L2: book must NOT re-ask when the conversation marker records acceptance.

    This reproduces QA V4 turn 11: update_booking cleared the gate, then the
    LLM called book WITHOUT policy_accepted=True. With the marker present,
    book must proceed AND persist the consent row.
    """
    from agent.tools.book import book

    customer = _make_customer_mock(policy_accepted_at=None, policy_version=None)
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://atrevetepeluqueria.com/politica-privacidad/"

    accept_policy_mock = AsyncMock(return_value=MagicMock())

    with (
        _fk_guards_ok(),
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch(
            "agent.tools.book.check_slot_availability",
            AsyncMock(return_value={"available": True}),
        ),
        patch("agent.tools.book.accept_policy", accept_policy_mock),
        patch(
            "agent.tools.book.get_conversation_policy_acceptance",
            AsyncMock(return_value="1.0"),
        ),
        patch("agent.tools.book.clear_conversation_policy_acceptance", AsyncMock()),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book._invalidate_cached_customer", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        # LLM dropped the flag — the QA V4 failure shape
        result_json = await book.coroutine(**_book_kwargs_with_conversation(policy_accepted=False))

    result = parse_response(result_json)
    assert (
        result.get("next_step") != "policy_acceptance_required"
    ), f"book re-asked for policy despite conversation marker (re-ask loop!): {result}"
    # Consent must be persisted as if the flag had been passed
    accept_policy_mock.assert_called_once()


@pytest.mark.asyncio
async def test_book_gate_still_rejects_without_flag_or_marker():
    """L2 (triangulation): no flag AND no marker → book gate rejects as before."""
    from agent.tools.book import book

    customer = _make_customer_mock(policy_accepted_at=None, policy_version=None)
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://atrevetepeluqueria.com/politica-privacidad/"

    with (
        _fk_guards_ok(),
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch(
            "agent.tools.book.check_slot_availability",
            AsyncMock(return_value={"available": True}),
        ),
        patch(
            "agent.tools.book.get_conversation_policy_acceptance",
            AsyncMock(return_value=None),
        ),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        result_json = await book.coroutine(**_book_kwargs_with_conversation(policy_accepted=False))

    result = parse_response(result_json)
    assert result["status"] == "rejected"
    assert (
        result.get("next_step") == "policy_acceptance_required"
    ), f"Gate must still reject without flag or marker: {result}"


@pytest.mark.asyncio
async def test_book_clears_marker_after_consent_commit():
    """L2: once the consent row is committed, the conversation marker is cleaned up."""
    from agent.tools.book import book

    customer = _make_customer_mock(policy_accepted_at=None, policy_version=None)
    ctx, session = _make_session_ctx(customer=customer)

    settings_mock = MagicMock()
    settings_mock.POLICY_VERSION = "1.0"
    settings_mock.POLICY_URL = "https://atrevetepeluqueria.com/politica-privacidad/"

    clear_marker_mock = AsyncMock()

    with (
        _fk_guards_ok(),
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools.book.get_settings", return_value=settings_mock),
        patch(
            "agent.tools.book.check_slot_availability",
            AsyncMock(return_value={"available": True}),
        ),
        patch("agent.tools.book.accept_policy", AsyncMock(return_value=MagicMock())),
        patch("agent.tools.book.clear_conversation_policy_acceptance", clear_marker_mock),
        patch("agent.tools.book.read_customer_memories", AsyncMock(return_value=None)),
        patch("agent.tools.book.write_customer_memories", AsyncMock()),
        patch("agent.services.gcal_push_service.fire_and_forget_push_appointment", AsyncMock()),
        patch("agent.tools.book._invalidate_cached_customer", AsyncMock()),
        patch("agent.tools.book.asyncio.create_task"),
    ):
        result_json = await book.coroutine(**_book_kwargs_with_conversation(policy_accepted=True))

    result = parse_response(result_json)
    assert result.get("next_step") != "policy_acceptance_required", f"Unexpected gate: {result}"
    clear_marker_mock.assert_called_once_with(CONVERSATION_ID)


# ---------------------------------------------------------------------------
# Conversation marker helpers — Redis fail-open contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_marker_set_writes_versioned_key_with_ttl():
    from agent.services.policy_service import set_conversation_policy_acceptance

    client = AsyncMock()
    with patch("shared.redis_client.get_redis_client", return_value=client):
        await set_conversation_policy_acceptance("conv-42", "1.0")

    client.setex.assert_called_once()
    key, ttl, value = client.setex.call_args[0]
    assert key == "policy_accepted:v2:conv-42"
    assert ttl > 0
    assert value == "1.0"


@pytest.mark.asyncio
async def test_marker_get_returns_version_string():
    from agent.services.policy_service import get_conversation_policy_acceptance

    client = AsyncMock()
    client.get = AsyncMock(return_value="1.0")
    with patch("shared.redis_client.get_redis_client", return_value=client):
        result = await get_conversation_policy_acceptance("conv-42")

    assert result == "1.0"
    client.get.assert_called_once_with("policy_accepted:v2:conv-42")


@pytest.mark.asyncio
async def test_marker_get_decodes_bytes():
    from agent.services.policy_service import get_conversation_policy_acceptance

    client = AsyncMock()
    client.get = AsyncMock(return_value=b"1.0")
    with patch("shared.redis_client.get_redis_client", return_value=client):
        result = await get_conversation_policy_acceptance("conv-42")

    assert result == "1.0"


@pytest.mark.asyncio
async def test_marker_helpers_fail_open_on_redis_errors():
    from agent.services.policy_service import (
        clear_conversation_policy_acceptance,
        get_conversation_policy_acceptance,
        set_conversation_policy_acceptance,
    )

    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionError("redis down"))
    client.setex = AsyncMock(side_effect=ConnectionError("redis down"))
    client.delete = AsyncMock(side_effect=ConnectionError("redis down"))
    with patch("shared.redis_client.get_redis_client", return_value=client):
        assert await get_conversation_policy_acceptance("conv-42") is None
        # Neither raises:
        await set_conversation_policy_acceptance("conv-42", "1.0")
        await clear_conversation_policy_acceptance("conv-42")


@pytest.mark.asyncio
async def test_marker_clear_deletes_key():
    from agent.services.policy_service import clear_conversation_policy_acceptance

    client = AsyncMock()
    with patch("shared.redis_client.get_redis_client", return_value=client):
        await clear_conversation_policy_acceptance("conv-42")

    client.delete.assert_called_once_with("policy_accepted:v2:conv-42")


# ---------------------------------------------------------------------------
# CustomerResolveMiddleware cache — policy_accepted_at JSON round-trip (latent crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cached_policy_accepted_at_string_coerced_to_datetime():
    """L2 discovery: Redis cache stores datetimes as strings (json default=str).

    On cache hit the middleware called `.strftime()` on a str → AttributeError.
    `_get_cached_customer` must coerce the ISO string back to datetime.
    """
    from datetime import datetime

    from agent.middleware.customer_resolve import _get_cached_customer

    cached_at = "2026-06-09 18:30:00.123456+00:00"
    raw = json.dumps(
        {
            "id": str(uuid4()),
            "name": "Ana García",
            "phone": "+34999000099",
            "is_returning": True,
            "notes": None,
            "policy_accepted_at": cached_at,
            "policy_version": "1.0",
        }
    )
    client = AsyncMock()
    client.get = AsyncMock(return_value=raw)
    with patch("agent.middleware.customer_resolve.get_redis_client", return_value=client):
        customer = await _get_cached_customer("+34999000099")

    assert customer is not None
    assert isinstance(customer["policy_accepted_at"], datetime), (
        "policy_accepted_at must be coerced back to datetime on cache read "
        f"(got {type(customer['policy_accepted_at'])})"
    )
    # The middleware renders it with strftime — must not raise
    assert customer["policy_accepted_at"].strftime("%d/%m/%Y")


@pytest.mark.asyncio
async def test_cached_policy_accepted_at_invalid_string_treated_as_none():
    """L2 (triangulation): unparseable cached value degrades to None (gate re-checks DB)."""
    from agent.middleware.customer_resolve import _get_cached_customer

    raw = json.dumps(
        {
            "id": str(uuid4()),
            "name": "Ana García",
            "phone": "+34999000099",
            "is_returning": True,
            "notes": None,
            "policy_accepted_at": "not-a-datetime",
            "policy_version": "1.0",
        }
    )
    client = AsyncMock()
    client.get = AsyncMock(return_value=raw)
    with patch("agent.middleware.customer_resolve.get_redis_client", return_value=client):
        customer = await _get_cached_customer("+34999000099")

    assert customer is not None
    assert customer["policy_accepted_at"] is None
