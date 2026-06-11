"""S1-T2.5 RED — CustomerResolveMiddleware persist delta with customer_memories.

Tests for Change S PR-2 customer_resolve migration:
- customer_memories added to Command(update=...) delta
- UUID coercion via persist_to_checkpoint
- Both customer_id and customer_memories present in Command

Spec: REQ-S1-8, Scenario S1-A
Design: ADR-1, customer_resolve.py migration spec
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(state: dict) -> MagicMock:
    """Build a minimal ModelRequest mock with a working override()."""
    from langchain_core.messages import SystemMessage

    req = MagicMock()
    req.state = state
    req.system_message = SystemMessage(content="base system")

    def override(**kwargs):
        new_state = {**state, **kwargs.get("state", {})}
        new_req = MagicMock()
        new_req.state = new_state
        new_req.system_message = kwargs.get("system_message", req.system_message)
        new_req.override = MagicMock(side_effect=lambda **kw: override(**kw))
        return new_req

    req.override = MagicMock(side_effect=override)
    return req


def _make_customer(customer_id: uuid.UUID) -> dict:
    """Build a minimal customer dict as returned by _lookup_customer."""
    return {
        "id": customer_id,  # stdlib uuid.UUID
        "name": "Test Customer",
        "phone": "+34999000001",
        "is_returning": True,
        "notes": None,
        "policy_accepted_at": None,
        "policy_version": None,
    }


def _make_memories() -> dict:
    """Build a customer memories dict as returned by read_customer_memories."""
    return {
        "visit_count": 5,
        "preferred_stylist_name": "Ana",
        "no_preference_stylist": False,
        "typical_services": ["Corte Dama"],
        "typical_day_of_week": "lunes",
        "typical_time_of_day": "mañana",
        "agent_notes": "Le gusta el corte en capas.",
    }


@contextmanager
def _patch_resolve_io(customer: dict, memories: dict):
    """Patch all I/O in CustomerResolveMiddleware."""
    with (
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            new_callable=AsyncMock,
            return_value=None,  # force DB path
        ),
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            new_callable=AsyncMock,
            return_value=customer,
        ),
        patch(
            "agent.middleware.customer_resolve.read_customer_memories",
            new_callable=AsyncMock,
            return_value=memories,
        ),
        patch(
            "agent.middleware.customer_resolve.get_redis_client",
            return_value=MagicMock(),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# S1-T2.5a — customer_memories in persist delta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_memories_in_persist_delta():
    """After resolve with memories, Command.update contains customer_memories.

    REQ-S1-8: CustomerResolveMiddleware must persist customer_memories alongside
    customer_id/customer_name via persist_to_checkpoint() Command.

    Spec: REQ-S1-8, Scenario S1-A
    """
    from langchain.agents.middleware import ExtendedModelResponse

    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    customer_id = uuid.uuid4()
    customer = _make_customer(customer_id)
    memories = _make_memories()

    state = {
        "customer_phone": "+34999000001",
        "customer_id": None,
        "customer_name": None,
        "messages": [],
        "conversation_id": "test-resolve-conv",
    }
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    response_from_handler = MagicMock()

    async def handler(req):
        return response_from_handler

    with _patch_resolve_io(customer, memories):
        result = await middleware.awrap_model_call(request, handler)

    assert isinstance(result, ExtendedModelResponse), (
        "CustomerResolveMiddleware must return ExtendedModelResponse when persisting fields. "
        "After S1-T2.6, customer_memories must be included in the Command delta."
    )
    update = result.command.update
    assert "customer_memories" in update, (
        f"'customer_memories' must be in Command.update. "
        f"Current update keys: {list(update.keys())}. "
        "REQ-S1-8: customer_memories must be persisted to LangGraph checkpoint."
    )
    assert update["customer_memories"] is not None, "customer_memories must be non-null"
    assert update["customer_memories"]["visit_count"] == 5


# ---------------------------------------------------------------------------
# S1-T2.5b — customer_id UUID coerced to str in Command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_id_uuid_coerced_to_str():
    """Command.update['customer_id'] must be str even when customer.id is uuid.UUID.

    REQ-S1-2: UUID coercion must happen via persist_to_checkpoint's coercion table.

    Spec: REQ-S1-2, REQ-S1-8, Scenario S1-A
    """
    from langchain.agents.middleware import ExtendedModelResponse

    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    customer_id = uuid.uuid4()  # stdlib uuid.UUID
    customer = _make_customer(customer_id)
    memories = _make_memories()

    state = {
        "customer_phone": "+34999000001",
        "customer_id": None,
        "customer_name": None,
        "messages": [],
        "conversation_id": "test-resolve-coerce-conv",
    }
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    async def handler(req):
        return MagicMock()

    with _patch_resolve_io(customer, memories):
        result = await middleware.awrap_model_call(request, handler)

    assert isinstance(result, ExtendedModelResponse)
    update = result.command.update

    cid = update.get("customer_id")
    assert isinstance(cid, str), (
        f"customer_id in Command.update must be str, got {type(cid).__name__!r}. "
        "UUID must be coerced by persist_to_checkpoint (ADR-1 coercion table)."
    )
    assert cid == str(
        customer_id
    ), f"customer_id must equal str(uuid), expected {str(customer_id)!r}, got {cid!r}."


# ---------------------------------------------------------------------------
# S1-T2.5c — customer_memories NOT in Command when memories is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_memories_not_in_delta_when_none():
    """customer_memories must NOT be added to delta when read_customer_memories returns None.

    Only add customer_memories to the persist delta when memories is not None.
    This avoids writing null values to checkpoint unnecessarily.

    Spec: REQ-S1-8 (condition: memories is not None)
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    customer_id = uuid.uuid4()
    customer = _make_customer(customer_id)

    state = {
        "customer_phone": "+34999000001",
        "customer_id": None,
        "customer_name": None,
        "messages": [],
        "conversation_id": "test-resolve-no-mem-conv",
    }
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    async def handler(req):
        return MagicMock()

    with _patch_resolve_io(customer, memories=None):
        result = await middleware.awrap_model_call(request, handler)

    # customer_id and customer_name should still be persisted
    if hasattr(result, "command") and result.command is not None:
        update = result.command.update or {}
        assert "customer_memories" not in update, (
            "'customer_memories' must NOT appear in Command.update when memories is None. "
            "Design spec: 'when memories is not None and differs from current state value'."
        )


# ---------------------------------------------------------------------------
# S1-T2.5d — both customer_id and customer_memories in same Command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_customer_id_and_memories_in_same_command():
    """customer_id and customer_memories are persisted together in a single Command.

    This avoids two separate ExtendedModelResponse wrappers in one middleware.
    persist_to_checkpoint handles both fields atomically.

    Spec: REQ-S1-8, ADR-1
    """
    from langchain.agents.middleware import ExtendedModelResponse

    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    customer_id = uuid.uuid4()
    customer = _make_customer(customer_id)
    memories = _make_memories()

    state = {
        "customer_phone": "+34999000001",
        "customer_id": None,
        "customer_name": None,
        "messages": [],
        "conversation_id": "test-resolve-atomic-conv",
    }
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    async def handler(req):
        return MagicMock()

    with _patch_resolve_io(customer, memories):
        result = await middleware.awrap_model_call(request, handler)

    assert isinstance(result, ExtendedModelResponse)
    update = result.command.update
    assert "customer_id" in update, "customer_id must be in Command.update"
    assert "customer_memories" in update, "customer_memories must be in Command.update"
    # Single Command — both fields in same update dict
    assert isinstance(update, dict)
