"""Tests for DynamicPromptMiddleware — updated for slot-based architecture (Tranche B)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, SystemMessage


class _FakeModelResponse:
    def __init__(self, msg):
        self.result = [msg]
        self.structured_response = None


@pytest.fixture()
def general_state():
    return {
        "messages": [],
        "customer_id": None,
        "customer_name": None,
    }


class FakeRequest:
    """Minimal request stub that captures override() calls."""

    def __init__(self, system_content: str = "base", state: dict | None = None):
        self.system_message = SystemMessage(content=system_content)
        self._state = dict(state or {})
        self._captured: dict = {}

    @property
    def state(self):
        return self._state

    def override(self, **kwargs):
        self._captured.update(kwargs)
        new = FakeRequest(state=kwargs.get("state", self._state))
        new.system_message = kwargs.get("system_message", self.system_message)
        new._captured = {}
        return new


@pytest.mark.asyncio
async def test_awrap_model_call_writes_catalog_slot(general_state):
    """Middleware must write catalog content to _slot_catalog state key."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    catalog_content = "## Catálogo\n- Corte: 30min"

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value=catalog_content),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        mw = DynamicPromptMiddleware()
        req = FakeRequest(state=general_state)

        final_state: dict = {}

        async def fake_handler(r):
            final_state.update(r.state)
            return _FakeModelResponse(AIMessage(content="hola"))

        await mw.awrap_model_call(req, fake_handler)

    assert "_slot_catalog" in final_state, "_slot_catalog must be written to state"
    assert catalog_content in final_state["_slot_catalog"]
    assert "<catalog>" in final_state["_slot_catalog"]


@pytest.mark.asyncio
async def test_catalog_slot_contains_catalog_section(general_state):
    """The _slot_catalog key must contain the catalog text wrapped in <catalog> tags."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    catalog_content = "## Catálogo\n- Tinte: 90min"

    final_state: dict = {}

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value=catalog_content),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={"martes": "10:00-20:00"}),
        ),
    ):
        mw = DynamicPromptMiddleware()
        req = FakeRequest(state=general_state)

        async def capturing_handler(r):
            final_state.update(r.state)
            return _FakeModelResponse(AIMessage(content="resp"))

        await mw.awrap_model_call(req, capturing_handler)

    assert catalog_content in final_state.get("_slot_catalog", "")
    # System message must NOT be mutated
    assert catalog_content not in req.system_message.content


@pytest.mark.asyncio
async def test_hours_slot_contains_hours(general_state):
    """Business hours snapshot must appear in _slot_business_hours state key."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    hours_content = {"martes": "10:00-20:00", "sabado": "09:00-14:00"}

    final_state: dict = {}

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value="## Catálogo"),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value=hours_content),
        ),
    ):
        mw = DynamicPromptMiddleware()
        req = FakeRequest(state=general_state)

        async def capturing_handler(r):
            final_state.update(r.state)
            return _FakeModelResponse(AIMessage(content="resp"))

        await mw.awrap_model_call(req, capturing_handler)

    hours_slot = final_state.get("_slot_business_hours", "")
    assert "10:00-20:00" in hours_slot or "martes" in hours_slot
    assert "<business_hours>" in hours_slot


@pytest.mark.asyncio
async def test_system_message_not_mutated(general_state):
    """DynamicPromptMiddleware must NOT mutate system_message.content."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    original_system = "base general prompt"

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value="catalog"),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={"martes": "10:00-20:00"}),
        ),
    ):
        mw = DynamicPromptMiddleware()
        req = FakeRequest(system_content=original_system, state=general_state)

        received_systems: list[str] = []

        async def capturing_handler(r):
            received_systems.append(r.system_message.content)
            return _FakeModelResponse(AIMessage(content="resp"))

        await mw.awrap_model_call(req, capturing_handler)

    # system_message.content must be unchanged — slots carry the data
    assert received_systems[0] == original_system
