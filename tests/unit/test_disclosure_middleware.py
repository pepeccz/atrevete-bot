"""T4.1 / T7.4 — DisclosureMiddleware: first turn emits disclosure; subsequent don't.

TDD RED phase — written before agent/middleware/disclosure.py exists.
"""

import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain.agents.middleware import ModelResponse


def _make_request(messages: list, system_message=None):
    """Build a minimal ModelRequest mock."""
    req = MagicMock()
    req.state = {"messages": messages}
    req.system_message = system_message or SystemMessage(content="base prompt")

    captured_overrides = {}

    def override(**kwargs):
        captured_overrides.update(kwargs)
        new_req = MagicMock()
        new_req.state = kwargs.get("state", req.state)
        new_req.system_message = kwargs.get("system_message", req.system_message)
        new_req.override = MagicMock(side_effect=lambda **kw: new_req)
        return new_req

    req.override = MagicMock(side_effect=override)
    return req


def _make_response(content: str = "Hello") -> ModelResponse:
    """Build a ModelResponse with a single AIMessage."""
    return ModelResponse(result=[AIMessage(content=content)])


def test_disclosure_middleware_importable():
    """DisclosureMiddleware is importable from agent.middleware.disclosure."""
    from agent.middleware.disclosure import DisclosureMiddleware

    assert callable(DisclosureMiddleware)


def test_disclosure_text_exported():
    """DISCLOSURE_TEXT constant is exported and non-empty."""
    from agent.middleware.disclosure import DISCLOSURE_TEXT

    assert isinstance(DISCLOSURE_TEXT, str)
    assert len(DISCLOSURE_TEXT) > 20


@pytest.mark.asyncio
async def test_disclosure_on_first_turn():
    """First turn (empty messages) → disclosure prepended to AI response content."""
    from agent.middleware.disclosure import DisclosureMiddleware, DISCLOSURE_TEXT

    middleware = DisclosureMiddleware()
    request = _make_request(messages=[])
    base_response = _make_response("¿En qué te puedo ayudar?")

    async def handler(req):
        return base_response

    result = await middleware.awrap_model_call(request, handler)

    # Result must be a ModelResponse
    assert isinstance(result, ModelResponse)
    # The first (and only) message must contain the disclosure text
    ai_msg = result.result[0]
    assert isinstance(ai_msg, AIMessage)
    assert DISCLOSURE_TEXT in ai_msg.content


@pytest.mark.asyncio
async def test_no_disclosure_on_subsequent_turn():
    """Second turn (prior messages exist) → disclosure NOT added to response."""
    from agent.middleware.disclosure import DisclosureMiddleware, DISCLOSURE_TEXT

    middleware = DisclosureMiddleware()
    prior_messages = [
        HumanMessage(content="Hola"),
        AIMessage(content=DISCLOSURE_TEXT + " ¿En qué te puedo ayudar?"),
    ]
    request = _make_request(messages=prior_messages)
    base_content = "¿Quieres reservar una cita?"
    base_response = _make_response(base_content)

    async def handler(req):
        return base_response

    result = await middleware.awrap_model_call(request, handler)

    assert isinstance(result, ModelResponse)
    ai_msg = result.result[0]
    assert isinstance(ai_msg, AIMessage)
    # Disclosure must NOT be in the subsequent turn response
    assert DISCLOSURE_TEXT not in ai_msg.content
    assert ai_msg.content == base_content
