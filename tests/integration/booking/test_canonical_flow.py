"""Integration test: canonical booking flow — Task 5.1 (booking-prompts-audit-fix).

Spec:
- ask_service leaf runs before ask_audience (step sequence preserved).
- 'bebé' is accepted as valid audience (maps to 'baby' via AudienceTag).
- Every leaf invocation receives a SystemMessage as the first message.
- preprocess never injects an AIMessage.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from agent.booking.schemas import AudienceResponse, ServiceSelectionResponse


def _make_structured_chain(response_obj):
    """Build a mock structured_output chain that captures its messages."""
    captured = []

    async def ainvoke(messages):
        captured.extend(messages)
        return response_obj

    chain = MagicMock()
    chain.ainvoke = ainvoke
    chain._captured = captured
    return chain


@pytest.mark.asyncio
async def test_ask_service_runs_before_ask_audience():
    """Booking FSM: step='service' → ask_service leaf runs and advances to 'audience'."""
    from agent.booking.leaves import ask_service

    uid = uuid4()
    resp = ServiceSelectionResponse(
        message="¿Qué servicio?",
        needs_clarification=False,
        selected_service_ids=[uid],
    )

    chain = _make_structured_chain(resp)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=chain)

    state = {
        "booking": {
            "step": "service",
            "service_ids": [],
            "audience": None,
        },
        "messages": [HumanMessage(content="quiero cortarme el pelo")],
        "conversation_id": "conv-1",
        "customer_phone": "+34600000000",
        "current_mode": "BOOKING",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
        "user_message": "quiero cortarme el pelo",
    }

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value="Corte — 30min"),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "09:00-18:00"}),
        ),
    ):
        result = await ask_service(state)

    # Step advanced to 'audience'
    assert result.update["booking"]["step"] == "audience"
    # audience must NOT have been written by ask_service
    assert result.update["booking"].get("audience") is None
    # First message to LLM was a SystemMessage
    assert isinstance(chain._captured[0], SystemMessage)


@pytest.mark.asyncio
async def test_ask_audience_accepts_baby():
    """ask_audience leaf accepts 'baby' as inferred_audience — AudienceTag has 6 values."""
    from agent.booking.leaves import ask_audience

    resp = AudienceResponse(message="Perfecto, para el bebé.", inferred_audience="baby")

    chain = _make_structured_chain(resp)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=chain)

    state = {
        "booking": {
            "step": "audience",
            "service_ids": [uuid4()],
            "audience": None,
        },
        "messages": [HumanMessage(content="es para mi bebé")],
        "conversation_id": "conv-1",
        "customer_phone": "+34600000000",
        "current_mode": "BOOKING",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
        "user_message": "es para mi bebé",
    }

    with (
        patch("agent.booking.leaves.get_llm", return_value=llm),
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        result = await ask_audience(state)

    assert result.update["booking"]["audience"] == "baby"
    assert result.update["booking"]["step"] == "stylist"
    # First message to LLM must be a SystemMessage
    assert isinstance(chain._captured[0], SystemMessage)
    # SystemMessage must contain 'bebé' in audience taxonomy
    system_content = chain._captured[0].content
    assert "bebé" in system_content or "bebe" in system_content.lower()


@pytest.mark.asyncio
async def test_preprocess_does_not_inject_greeting():
    """Preprocess must not add AIMessage on first turn (empty history)."""
    from langchain_core.messages import AIMessage

    from agent.nodes.preprocess import preprocess_node

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    state = {
        "conversation_id": "conv-1",
        "customer_phone": "+34600000000",
        "user_message": "hola",
        "pending_whatsapp_name": None,
        "current_mode": "GENERAL",
        "messages": [],  # empty = first turn
        "booking": None,
        "customer_id": None,
        "customer_name": None,
    }

    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    new_messages = result.update.get("messages", [])
    ai_msgs = [m for m in new_messages if isinstance(m, AIMessage)]
    assert len(ai_msgs) == 0
    assert len(new_messages) == 1
    assert isinstance(new_messages[0], HumanMessage)
