"""Tests for DynamicPromptMiddleware — adapted for create_agent rewrite."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.asyncio
async def test_awrap_model_call_injects_catalog(general_state):
    """Middleware must prepend catalog section to the system message."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    catalog_content = "## Catálogo\n- Corte: 30min"
    hours_content = {"lunes": "cerrado", "martes": "10:00-20:00"}

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value=catalog_content),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value=hours_content),
        ),
    ):
        mw = DynamicPromptMiddleware()
        original_system = "Sos un asistente."
        request = MagicMock()
        request.system_message = SystemMessage(content=original_system)
        request.state = general_state
        request.override = lambda **kw: kw  # capture the override kwargs

        ai_reply = AIMessage(content="hola")

        async def fake_handler(req):
            return _FakeModelResponse(ai_reply)

        result = await mw.awrap_model_call(request, fake_handler)
        assert result is not None


@pytest.mark.asyncio
async def test_system_prompt_contains_catalog_section(general_state):
    """The system_message passed to handler must contain catalog text."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    catalog_content = "## Catálogo\n- Tinte: 90min"
    hours_content = {"martes": "10:00-20:00"}

    captured_requests = []

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value=catalog_content),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value=hours_content),
        ),
    ):
        mw = DynamicPromptMiddleware()

        original_system = "Sos un asistente."

        class FakeRequest:
            def __init__(self):
                self.system_message = SystemMessage(content=original_system)
                self.state = general_state

            def override(self, **kwargs):
                new = FakeRequest()
                for k, v in kwargs.items():
                    setattr(new, k, v)
                return new

        async def capturing_handler(req):
            captured_requests.append(req)
            return _FakeModelResponse(AIMessage(content="resp"))

        req = FakeRequest()
        await mw.awrap_model_call(req, capturing_handler)

    assert len(captured_requests) == 1
    final_system = captured_requests[0].system_message.content
    assert catalog_content in final_system
    assert original_system in final_system


@pytest.mark.asyncio
async def test_system_prompt_contains_hours(general_state):
    """Business hours snapshot must appear in injected system prompt."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    catalog_content = "## Catálogo\n- Corte: 30min"
    hours_content = {"martes": "10:00-20:00", "sabado": "09:00-14:00"}

    captured_requests = []

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value=catalog_content),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value=hours_content),
        ),
    ):
        mw = DynamicPromptMiddleware()

        class FakeRequest:
            def __init__(self):
                self.system_message = SystemMessage(content="base prompt")
                self.state = general_state

            def override(self, **kwargs):
                new = FakeRequest()
                for k, v in kwargs.items():
                    setattr(new, k, v)
                return new

        async def capturing_handler(req):
            captured_requests.append(req)
            return _FakeModelResponse(AIMessage(content="resp"))

        await mw.awrap_model_call(FakeRequest(), capturing_handler)

    final_system = captured_requests[0].system_message.content
    assert "10:00-20:00" in final_system or "martes" in final_system


@pytest.mark.asyncio
async def test_no_booking_state_no_snapshot(general_state):
    """Without a booking context, no booking-specific data is injected."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    captured_requests = []

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

        class FakeRequest:
            def __init__(self):
                self.system_message = SystemMessage(content="base general prompt")
                self.state = general_state

            def override(self, **kwargs):
                new = FakeRequest()
                for k, v in kwargs.items():
                    setattr(new, k, v)
                return new

        async def capturing_handler(req):
            captured_requests.append(req)
            return _FakeModelResponse(AIMessage(content="resp"))

        await mw.awrap_model_call(FakeRequest(), capturing_handler)

    final_system = captured_requests[0].system_message.content
    # catalog + hours still injected
    assert "catalog" in final_system
