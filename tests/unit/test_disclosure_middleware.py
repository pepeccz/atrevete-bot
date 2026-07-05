"""T4.1 / T7.4 — DisclosureMiddleware: first turn emits disclosure; subsequent don't.

TDD RED phase — written before agent/middleware/disclosure.py exists.
"""

import logging
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


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
    from agent.middleware.disclosure import DISCLOSURE_TEXT, DisclosureMiddleware

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
    from agent.middleware.disclosure import DISCLOSURE_TEXT, DisclosureMiddleware

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


# --- T1: New assertions for Maite identity spec ---


def test_disclosure_text_contains_maite():
    """DISCLOSURE_TEXT must identify the assistant as 'Maite'."""
    from agent.middleware.disclosure import DISCLOSURE_TEXT

    assert "Maite" in DISCLOSURE_TEXT


def test_disclosure_text_contains_asistenta_virtual_con_ia():
    """DISCLOSURE_TEXT must identify the assistant as 'asistenta virtual con IA'.

    NOTE: The phrasing changed from 'IA, no una persona' to 'asistenta virtual con IA'
    which is more natural and still EU AI Act compliant (identifies as AI assistant).
    """
    from agent.middleware.disclosure import DISCLOSURE_TEXT

    assert "asistenta virtual con IA" in DISCLOSURE_TEXT


def test_disclosure_text_contains_atrevete():
    """DISCLOSURE_TEXT must identify the salon (Atrévete).

    NOTE: 'hablar con alguien' was removed from the DISCLOSURE_TEXT in the create_agent
    rewrite — the escalation option is handled by [R7] in critical_rules.md rather than
    being hard-coded in the greeting banner. The text now identifies the salon by name.
    """
    from agent.middleware.disclosure import DISCLOSURE_TEXT

    assert "Atrévete" in DISCLOSURE_TEXT


def test_disclosure_text_does_not_contain_asistente_ia():
    """DISCLOSURE_TEXT must NOT use generic 'asistente IA' label (spec §1, ADR-1)."""
    from agent.middleware.disclosure import DISCLOSURE_TEXT

    assert "asistente IA" not in DISCLOSURE_TEXT


# ---------------------------------------------------------------------------
# sdd/context-coherence TASK-17/18 (Stream 4, D10) — disclosure.turn_evaluated log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disclosure_logs_turn_evaluated_first_turn(caplog):
    """First turn: disclosure.turn_evaluated logs is_first_turn=True, no PII."""
    from agent.middleware.disclosure import DisclosureMiddleware

    middleware = DisclosureMiddleware()
    request = _make_request(messages=[])
    request.state["conversation_id"] = "conv-123"
    base_response = _make_response("¿En qué te puedo ayudar?")

    async def handler(req):
        return base_response

    with caplog.at_level(logging.INFO, logger="agent.middleware.disclosure"):
        await middleware.awrap_model_call(request, handler)

    matching = [r for r in caplog.records if r.getMessage() == "disclosure.turn_evaluated"]
    assert matching, f"Expected a 'disclosure.turn_evaluated' log record, got: {caplog.records}"
    record = matching[0]
    assert record.conversation_id == "conv-123"
    assert record.is_first_turn is True
    assert record.prior_message_count == 0


@pytest.mark.asyncio
async def test_disclosure_logs_turn_evaluated_subsequent_turn(caplog):
    """Subsequent turn: is_first_turn=False, prior_message_count reflects history."""
    from agent.middleware.disclosure import DISCLOSURE_TEXT, DisclosureMiddleware

    middleware = DisclosureMiddleware()
    prior_messages = [
        HumanMessage(content="Hola"),
        AIMessage(content=DISCLOSURE_TEXT + " ¿En qué te puedo ayudar?"),
    ]
    request = _make_request(messages=prior_messages)
    request.state["conversation_id"] = "conv-456"
    base_response = _make_response("¿Quieres reservar una cita?")

    async def handler(req):
        return base_response

    with caplog.at_level(logging.INFO, logger="agent.middleware.disclosure"):
        await middleware.awrap_model_call(request, handler)

    matching = [r for r in caplog.records if r.getMessage() == "disclosure.turn_evaluated"]
    assert matching, f"Expected a 'disclosure.turn_evaluated' log record, got: {caplog.records}"
    record = matching[0]
    assert record.conversation_id == "conv-456"
    assert record.is_first_turn is False
    assert record.prior_message_count == 2


@pytest.mark.asyncio
async def test_disclosure_log_contains_no_message_content(caplog):
    """PII-safety: the log record must not leak raw message text."""
    from agent.middleware.disclosure import DisclosureMiddleware

    middleware = DisclosureMiddleware()
    prior_messages = [HumanMessage(content="mi telefono es 611222333 y me llamo Ana")]
    request = _make_request(messages=prior_messages)
    request.state["conversation_id"] = "conv-789"
    base_response = _make_response("Hola")

    async def handler(req):
        return base_response

    with caplog.at_level(logging.INFO, logger="agent.middleware.disclosure"):
        await middleware.awrap_model_call(request, handler)

    for record in caplog.records:
        assert "611222333" not in record.getMessage()
        assert "Ana" not in record.getMessage()
