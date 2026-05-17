"""T-01 — DisclosureMiddleware: _has_textual_ai_message predicate + first-turn injection.

RED phase: tests for the refactored predicate-based first-turn detection.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _make_request(messages: list):
    req = MagicMock()
    req.state = {"messages": messages}
    req.override = MagicMock(side_effect=lambda **kw: req)
    return req


def _make_response(content: str = "Hola") -> ModelResponse:
    return ModelResponse(result=[AIMessage(content=content)])


def _make_tool_call_response() -> ModelResponse:
    """AIMessage with tool_calls and empty content — tool-loop pass."""
    msg = AIMessage(content="", tool_calls=[{"name": "update_booking", "args": {}, "id": "tc1"}])
    return ModelResponse(result=[msg])


# ---------------------------------------------------------------------------
# T-01a: _has_textual_ai_message predicate
# ---------------------------------------------------------------------------


def test_predicate_empty_list_is_false():
    """Empty list → no textual AI message → returns False."""
    from agent.middleware.disclosure import _has_textual_ai_message

    assert _has_textual_ai_message([]) is False


def test_predicate_only_human_message_is_false():
    """[HumanMessage] → no AI message → returns False."""
    from agent.middleware.disclosure import _has_textual_ai_message

    assert _has_textual_ai_message([HumanMessage(content="Hola")]) is False


def test_predicate_ai_with_tool_calls_empty_content_is_false():
    """[Human, AIMessage(tool_calls, content='')] → tool-loop pass 1 → returns False."""
    from agent.middleware.disclosure import _has_textual_ai_message

    ai = AIMessage(content="", tool_calls=[{"name": "update_booking", "args": {}, "id": "tc1"}])
    assert _has_textual_ai_message([HumanMessage(content="Hola"), ai]) is False


def test_predicate_ai_with_tool_calls_and_tool_message_is_false():
    """[Human, AIMessage(tool_calls, ''), ToolMessage] → tool-loop pass 2, still first turn → False."""
    from agent.middleware.disclosure import _has_textual_ai_message

    ai = AIMessage(content="", tool_calls=[{"name": "update_booking", "args": {}, "id": "tc1"}])
    tool_msg = ToolMessage(content='{"next_step":"service_required"}', tool_call_id="tc1")
    assert _has_textual_ai_message([HumanMessage(content="Hola"), ai, tool_msg]) is False


def test_predicate_ai_with_text_content_is_true():
    """[Human, AIMessage(content='Hola'), Human] → textual AI message exists → True."""
    from agent.middleware.disclosure import _has_textual_ai_message

    ai = AIMessage(content="Hola, ¿en qué te puedo ayudar?")
    assert _has_textual_ai_message([HumanMessage(content="Hola"), ai, HumanMessage(content="Reserva")]) is True


def test_predicate_ai_with_whitespace_only_content_is_false():
    """AIMessage with content='   ' (whitespace only) → treated as empty → False."""
    from agent.middleware.disclosure import _has_textual_ai_message

    ai = AIMessage(content="   ")
    assert _has_textual_ai_message([HumanMessage(content="Hola"), ai]) is False


# ---------------------------------------------------------------------------
# T-01b: middleware prepends disclosure on first turn (no prior textual AI)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disclosure_prepended_on_first_turn_empty_state():
    """Empty prior messages → disclosure prepended to first textual AIMessage."""
    from agent.middleware.disclosure import DISCLOSURE_TEXT, DisclosureMiddleware

    mw = DisclosureMiddleware()
    request = _make_request(messages=[])
    response = _make_response("¿En qué te puedo ayudar?")

    async def handler(req):
        return response

    result = await mw.awrap_model_call(request, handler)
    assert isinstance(result, ModelResponse)
    ai = result.result[0]
    assert isinstance(ai, AIMessage)
    assert DISCLOSURE_TEXT in ai.content


@pytest.mark.asyncio
async def test_disclosure_prepended_when_prior_messages_have_only_human():
    """Prior = [HumanMessage] (tool-loop start) → still first turn → disclosure prepended."""
    from agent.middleware.disclosure import DISCLOSURE_TEXT, DisclosureMiddleware

    mw = DisclosureMiddleware()
    request = _make_request(messages=[HumanMessage(content="Hola")])
    response = _make_response("¿Te ayudo con una reserva?")

    async def handler(req):
        return response

    result = await mw.awrap_model_call(request, handler)
    ai = result.result[0]
    assert DISCLOSURE_TEXT in ai.content


@pytest.mark.asyncio
async def test_disclosure_NOT_prepended_on_tool_call_only_response():
    """First turn but response has only tool-call AIMessage (empty content) → no prepend."""
    from agent.middleware.disclosure import DISCLOSURE_TEXT, DisclosureMiddleware

    mw = DisclosureMiddleware()
    request = _make_request(messages=[HumanMessage(content="Hola")])
    response = _make_tool_call_response()

    async def handler(req):
        return response

    result = await mw.awrap_model_call(request, handler)
    ai = result.result[0]
    # content is empty — disclosure must NOT be injected into a tool-call-only AIMessage
    assert DISCLOSURE_TEXT not in ai.content


@pytest.mark.asyncio
async def test_disclosure_NOT_prepended_when_prior_textual_ai_exists():
    """Prior messages include a textual AIMessage → subsequent turn → no disclosure."""
    from agent.middleware.disclosure import DISCLOSURE_TEXT, DisclosureMiddleware

    mw = DisclosureMiddleware()
    prior = [
        HumanMessage(content="Hola"),
        AIMessage(content=DISCLOSURE_TEXT + " ¿En qué te puedo ayudar?"),
    ]
    request = _make_request(messages=prior)
    response = _make_response("¿Quieres reservar?")

    async def handler(req):
        return response

    result = await mw.awrap_model_call(request, handler)
    ai = result.result[0]
    assert DISCLOSURE_TEXT not in ai.content
    assert ai.content == "¿Quieres reservar?"
