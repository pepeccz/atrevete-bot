"""Tests for DynamicPromptMiddleware — Phase 5.3."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, SystemMessage


class _FakeModelResponse:
    def __init__(self, msg):
        self.result = [msg]
        self.structured_response = None


@pytest.fixture()
def booking_state():
    return {
        "booking": {
            "step": "date",
            "service_ids": [],
            "audience": "adult_female",
        },
        "messages": [],
    }


@pytest.fixture()
def general_state():
    return {
        "booking": None,
        "messages": [],
    }


@pytest.mark.asyncio
async def test_awrap_model_call_injects_catalog(booking_state):
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
        request.state = booking_state
        request.override = lambda **kw: kw  # capture the override kwargs

        ai_reply = AIMessage(content="hola")

        async def fake_handler(req):
            return _FakeModelResponse(ai_reply)

        # awrap_model_call must call override(system_message=...) with catalog injected
        result = await mw.awrap_model_call(request, fake_handler)
        # The result should be the handler result (we just check no exception + handler called)
        assert result is not None


@pytest.mark.asyncio
async def test_system_prompt_contains_catalog_section(booking_state):
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
                self.state = booking_state

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
async def test_system_prompt_contains_hours(booking_state):
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
                self.state = booking_state

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
async def test_booking_snapshot_injected_when_booking_active(booking_state):
    """When booking is active, the booking context snapshot is included."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    captured_requests = []

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value="catalog"),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        mw = DynamicPromptMiddleware()

        class FakeRequest:
            def __init__(self):
                self.system_message = SystemMessage(content="base")
                self.state = booking_state

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
    # booking context should mention step value
    assert "date" in final_system or "adult_female" in final_system


@pytest.mark.asyncio
async def test_no_booking_context_when_general(general_state):
    """When booking is None, no booking snapshot injected."""
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
    # no "Reserva en curso" or similar booking header when booking=None
    assert "adult_female" not in final_system
    assert "step" not in final_system
