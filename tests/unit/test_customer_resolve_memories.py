"""
Unit tests for CustomerResolveMiddleware memory enrichment (Phase 4).

Spec Domain 3 scenarios:
  1. Returning customer with full memories → slot includes all memory fields
  2. Returning customer with partial memories → slot includes only present fields
  3. New customer with no memories → slot has no memories section
  4. typical_services capped at 3 entries

D5 scenarios:
  5. Customer with non-null staff notes → <customer_staff_notes> block emitted
  6. Customer with null staff notes → no <customer_staff_notes> block

All tests mock _lookup_customer and read_customer_memories — no real DB/Redis.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest


def _make_request(state: dict):
    """Build a minimal ModelRequest mock."""
    from langchain_core.messages import SystemMessage

    req = MagicMock()
    req.state = state
    req.system_message = SystemMessage(content="base")
    captured = {}

    def override(**kwargs):
        captured.update(kwargs)
        new_req = MagicMock()
        new_req.state = {**state, **kwargs.get("state", {})}
        new_req.system_message = kwargs.get("system_message", req.system_message)
        new_req.override = MagicMock(return_value=new_req)
        new_req.captured = captured
        return new_req

    req.override = MagicMock(side_effect=override)
    req.captured = captured
    return req


def _make_response():
    resp = MagicMock()
    resp.content = "ok"
    return resp


CUSTOMER_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

FULL_MEMORIES = {
    "visit_count": 4,
    "preferred_stylist_id": "uuid-pilar",
    "preferred_stylist_name": "Pilar",
    "typical_services": ["Corte Dama", "Tinte", "Mechas", "Manicura", "Pedicura"],
    "typical_day_of_week": "viernes",
    "typical_time_of_day": "afternoon",
    "agent_notes": "Prefiere cita temprana, alérgica al amoniaco",
    "no_preference_stylist": False,
    "last_visit_date": "2026-04-15",
    "last_stylist_name": "Pilar",
}

PARTIAL_MEMORIES = {
    "visit_count": 1,
    "typical_services": ["Corte Dama"],
    "preferred_stylist_name": None,
    "agent_notes": None,
    "no_preference_stylist": False,
}


@pytest.mark.asyncio
async def test_slot_includes_all_memory_fields_for_full_memories():
    """
    GIVEN a returning customer with full memories (preferred_stylist, 5 services, agent_notes)
    WHEN CustomerResolveMiddleware resolves the customer
    THEN _slot_customer includes preferred_stylist_name, 3 most recent typical_services, agent_notes
    AND AgentState.customer_memories holds the full raw memories dict
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    state = {"customer_phone": "+34600000001", "customer_id": None, "messages": []}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_state = {}

    async def handler(req):
        injected_state.update(req.state)
        return _make_response()

    fake_customer = {
        "id": CUSTOMER_ID,
        "name": "María García",
        "is_returning": True,
        "notes": None,
    }

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new_callable=AsyncMock,
        return_value=fake_customer,
    ), patch(
        "agent.middleware.customer_resolve.read_customer_memories",
        new_callable=AsyncMock,
        return_value=FULL_MEMORIES,
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_state.get("_slot_customer", "")
    # Memory block present for returning customer with full memories
    assert "Pilar" in slot, "preferred_stylist_name must appear in slot"
    assert "Corte Dama" in slot, "typical_services must appear in slot"
    # Services capped at 3
    assert "Manicura" not in slot, "4th service must not appear in slot"
    assert "Pedicura" not in slot, "5th service must not appear in slot"
    assert "alérgica" in slot, "agent_notes must appear in slot"
    # Raw memories in state
    assert injected_state.get("customer_memories") == FULL_MEMORIES


@pytest.mark.asyncio
async def test_slot_includes_only_present_fields_for_partial_memories():
    """
    GIVEN a returning customer with only typical_services (1 entry) and no agent_notes
    WHEN CustomerResolveMiddleware resolves the customer
    THEN _slot_customer includes only typical_services
    AND preferred_stylist_name and agent_notes are absent from the slot
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    state = {"customer_phone": "+34600000002", "customer_id": None, "messages": []}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_state = {}

    async def handler(req):
        injected_state.update(req.state)
        return _make_response()

    fake_customer = {
        "id": CUSTOMER_ID,
        "name": "Ana Torres",
        "is_returning": True,
        "notes": None,
    }

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new_callable=AsyncMock,
        return_value=fake_customer,
    ), patch(
        "agent.middleware.customer_resolve.read_customer_memories",
        new_callable=AsyncMock,
        return_value=PARTIAL_MEMORIES,
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_state.get("_slot_customer", "")
    assert "Corte Dama" in slot, "typical_services must appear"
    assert "Estilista preferido" not in slot, "no preferred_stylist line when None"
    assert "Notas del bot" not in slot, "no agent_notes line when None"


@pytest.mark.asyncio
async def test_slot_has_no_memories_section_for_new_customer():
    """
    GIVEN a new customer with no memories
    WHEN CustomerResolveMiddleware resolves the customer
    THEN _slot_customer contains no memories section
    AND AgentState.customer_memories is None
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    state = {"customer_phone": "+34600000003", "customer_id": None, "messages": []}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_state = {}

    async def handler(req):
        injected_state.update(req.state)
        return _make_response()

    fake_customer = {
        "id": CUSTOMER_ID,
        "name": "Luis Gómez",
        "is_returning": False,
        "notes": None,
    }

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new_callable=AsyncMock,
        return_value=fake_customer,
    ), patch(
        "agent.middleware.customer_resolve.read_customer_memories",
        new_callable=AsyncMock,
        return_value=None,
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_state.get("_slot_customer", "")
    # No memory-specific fields
    assert "Visitas previas" not in slot
    assert "Estilista preferido" not in slot
    assert "Notas del bot" not in slot
    assert injected_state.get("customer_memories") is None


@pytest.mark.asyncio
async def test_typical_services_capped_at_3():
    """
    GIVEN a customer with more than 3 typical_services entries
    WHEN CustomerResolveMiddleware enriches _slot_customer
    THEN only the 3 most recent entries appear in the slot
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    state = {"customer_phone": "+34600000004", "customer_id": None, "messages": []}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_state = {}

    async def handler(req):
        injected_state.update(req.state)
        return _make_response()

    fake_customer = {
        "id": CUSTOMER_ID,
        "name": "Carmen Ruiz",
        "is_returning": True,
        "notes": None,
    }
    memories_with_many_services = {
        "visit_count": 5,
        "typical_services": ["SvcA", "SvcB", "SvcC", "SvcD", "SvcE"],
        "preferred_stylist_name": None,
        "agent_notes": None,
    }

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new_callable=AsyncMock,
        return_value=fake_customer,
    ), patch(
        "agent.middleware.customer_resolve.read_customer_memories",
        new_callable=AsyncMock,
        return_value=memories_with_many_services,
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_state.get("_slot_customer", "")
    # Only first 3 services must appear
    assert "SvcA" in slot
    assert "SvcB" in slot
    assert "SvcC" in slot
    assert "SvcD" not in slot
    assert "SvcE" not in slot


@pytest.mark.asyncio
async def test_staff_notes_emitted_when_present():
    """
    D5: Customer.notes is non-null/non-whitespace → <customer_staff_notes> block emitted.
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    state = {"customer_phone": "+34600000005", "customer_id": None, "messages": []}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_state = {}

    async def handler(req):
        injected_state.update(req.state)
        return _make_response()

    fake_customer = {
        "id": CUSTOMER_ID,
        "name": "Elena Sanz",
        "is_returning": True,
        "notes": "Alérgica a parabenos. Usa siempre tinte sin amoniaco.",
    }

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new_callable=AsyncMock,
        return_value=fake_customer,
    ), patch(
        "agent.middleware.customer_resolve.read_customer_memories",
        new_callable=AsyncMock,
        return_value=None,
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_state.get("_slot_customer", "")
    assert "<customer_staff_notes>" in slot, "Staff notes block must be emitted"
    assert "Alérgica a parabenos" in slot, "Staff notes content must appear"
    assert "</customer_staff_notes>" in slot, "Closing tag must be present"


@pytest.mark.asyncio
async def test_staff_notes_not_emitted_when_null():
    """
    D5: Customer.notes is null → no <customer_staff_notes> block.
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    state = {"customer_phone": "+34600000006", "customer_id": None, "messages": []}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_state = {}

    async def handler(req):
        injected_state.update(req.state)
        return _make_response()

    fake_customer = {
        "id": CUSTOMER_ID,
        "name": "Sofía Martínez",
        "is_returning": False,
        "notes": None,
    }

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new_callable=AsyncMock,
        return_value=fake_customer,
    ), patch(
        "agent.middleware.customer_resolve.read_customer_memories",
        new_callable=AsyncMock,
        return_value=None,
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_state.get("_slot_customer", "")
    assert "<customer_staff_notes>" not in slot, "Staff notes block must NOT appear when null"
