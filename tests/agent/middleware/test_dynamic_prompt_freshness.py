"""DynamicPromptMiddleware freshness test — updated for slot-based architecture (Tranche B).

Verifies that catalog_builder is called EACH turn (per-invocation),
NOT cached at graph compile time. The catalog content must differ
between two independent middleware invocations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, SystemMessage


class _FakeResponse:
    def __init__(self, msg):
        self.result = [msg]
        self.structured_response = None


class FakeRequest:
    def __init__(self, base="base prompt", state=None):
        self.system_message = SystemMessage(content=base)
        self._state = dict(state or {"booking": None, "messages": []})

    @property
    def state(self):
        return self._state

    def override(self, **kwargs):
        new = FakeRequest(state=kwargs.get("state", self._state))
        new.system_message = kwargs.get("system_message", self.system_message)
        return new


@pytest.mark.asyncio
async def test_catalog_called_per_turn_not_cached():
    """catalog_builder must be called on EACH middleware invocation (not cached)."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    call_count = 0
    catalog_values = ["CATALOG_V1", "CATALOG_V2"]

    async def mock_catalog_builder():
        nonlocal call_count
        val = catalog_values[call_count % len(catalog_values)]
        call_count += 1
        return val

    captured_states: list[dict] = []

    async def capturing_handler(req):
        captured_states.append(dict(req.state))
        return _FakeResponse(AIMessage(content="ok"))

    with (
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=mock_catalog_builder,
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        mw = DynamicPromptMiddleware()

        # First invocation
        await mw.awrap_model_call(FakeRequest(), capturing_handler)
        # Second invocation
        await mw.awrap_model_call(FakeRequest(), capturing_handler)

    assert call_count == 2, f"catalog_builder should be called twice, got {call_count}"
    assert len(captured_states) == 2

    first_catalog = captured_states[0].get("_slot_catalog", "")
    second_catalog = captured_states[1].get("_slot_catalog", "")

    assert "CATALOG_V1" in first_catalog, f"First call should inject CATALOG_V1. Got: {first_catalog!r}"
    assert "CATALOG_V2" in second_catalog, f"Second call should inject CATALOG_V2. Got: {second_catalog!r}"
    assert first_catalog != second_catalog, "Catalog slots must differ between turns (not cached)"


@pytest.mark.asyncio
async def test_middleware_not_stateful_between_instances():
    """Two separate DynamicPromptMiddleware instances must not share cached state."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    call_count = 0

    async def counting_catalog():
        nonlocal call_count
        call_count += 1
        return f"CATALOG_CALL_{call_count}"

    captured: list[str] = []

    async def handler(req):
        captured.append(req.state.get("_slot_catalog", ""))
        return _FakeResponse(AIMessage(content="ok"))

    with (
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=counting_catalog,
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        mw1 = DynamicPromptMiddleware()
        mw2 = DynamicPromptMiddleware()

        await mw1.awrap_model_call(FakeRequest(), handler)
        await mw2.awrap_model_call(FakeRequest(), handler)

    assert call_count == 2, f"Expected 2 catalog calls (one per instance), got {call_count}"
    assert "CATALOG_CALL_1" in captured[0]
    assert "CATALOG_CALL_2" in captured[1]
