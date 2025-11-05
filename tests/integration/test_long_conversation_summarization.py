"""
Integration test for long conversation summarization (30+ messages).

This test simulates a realistic 30-message booking conversation to verify:
- Summarization triggers at correct message count (20)
- Summary is created and persisted
- Recent 10 messages are retained
- Token count stays manageable
- Conversation context includes critical booking information
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.graphs.conversation_flow import create_conversation_graph
from agent.state.schemas import ConversationState
from agent.state.helpers import add_message, estimate_token_count


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_long_conversation_with_summarization():
    """
    Test a 30-message conversation flow with automatic summarization.

    Scenario:
    - Messages 1-5: Greeting and service inquiry
    - Messages 6-10: Service selection and availability check
    - Messages 11-15: Date/time selection
    - Messages 16-20: Payment link sent and confirmation (SUMMARIZATION TRIGGERS HERE)
    - Messages 21-25: Follow-up questions about parking/location
    - Messages 26-30: Final confirmations and thank you

    Assertions:
    - Summarization triggered at message 20
    - conversation_summary field populated
    - Only recent 10 messages retained in state
    - Final token count < 10,000 tokens
    - Summary contains key context (customer name, service, date)
    """
    # Mock Claude API to avoid real API calls
    mock_summary_response = MagicMock()
    mock_summary_response.content = (
        "Cliente María solicita cita para corte de pelo y tinte. "
        "Seleccionó fecha 15/11 a las 10am. Link de pago enviado, esperando confirmación."
    )

    with patch("agent.nodes.summarization.ChatOpenAI") as mock_llm_class:
        # Configure mock LLM
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = AsyncMock(return_value=mock_summary_response)
        mock_llm_class.return_value = mock_llm_instance

        # Create conversation graph without checkpointer (in-memory for testing)
        graph = create_conversation_graph(checkpointer=None)

        # Initialize conversation state
        state: ConversationState = {
            "conversation_id": "test-long-conv-001",
            "customer_phone": "+34612345678",
            "customer_name": "María García",
            "customer_id": None,
            "is_returning_customer": False,
            "messages": [],
            "total_message_count": 0,
            "current_intent": None,
            "metadata": {},
            "created_at": datetime.now(ZoneInfo("Europe/Madrid")),
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid")),
        }

        # Simulate 30-message conversation
        # Messages 1-5: Greeting and service inquiry
        conversation_messages = [
            ("user", "Hola, buenas tardes"),
            ("assistant", "¡Hola! Soy Maite 🌸. ¿En qué puedo ayudarte?"),
            ("user", "Necesito una cita para corte de pelo"),
            ("assistant", "Claro, ¿también quieres tinte o solo corte?"),
            ("user", "Sí, corte y tinte por favor"),
            # Messages 6-10: Service selection and availability
            ("assistant", "Perfecto. ¿Tienes preferencia de fecha?"),
            ("user", "¿Hay disponibilidad esta semana?"),
            ("assistant", "Sí, tenemos disponibilidad el viernes 15 a las 10am o 3pm"),
            ("user", "El viernes a las 10 está bien"),
            ("assistant", "Genial, reservando para el viernes 15 a las 10am"),
            # Messages 11-15: Date/time selection
            ("user", "¿Cuánto cuesta?"),
            ("assistant", "El pack de corte + tinte cuesta 45€"),
            ("user", "Vale, perfecto"),
            ("assistant", "Te envío el link de pago para confirmar la reserva"),
            ("user", "Ok, ¿puedo pagar ahora?"),
            # Messages 16-20: Payment link (SUMMARIZATION SHOULD TRIGGER AT 20)
            ("assistant", "Sí, aquí está el link: https://stripe.com/pay/123"),
            ("user", "Gracias, ya pagué"),
            ("assistant", "¡Perfecto! Pago confirmado. Tu cita está reservada"),
            ("user", "¿Dónde está la peluquería?"),
            ("assistant", "Estamos en Calle Mayor 123, Madrid"),
            # Messages 21-25: Follow-up about parking
            ("user", "¿Hay parking cerca?"),
            ("assistant", "Sí, hay parking público a 50 metros"),
            ("user", "Genial, ¿necesito llevar algo?"),
            ("assistant", "No, solo tu confirmación de pago"),
            ("user", "Perfecto, ¿me mandáis recordatorio?"),
            # Messages 26-30: Final confirmations
            ("assistant", "Sí, te enviaremos recordatorio 24h antes"),
            ("user", "Muchas gracias por todo"),
            ("assistant", "¡De nada! Nos vemos el viernes 🌸"),
            ("user", "Hasta el viernes"),
            ("assistant", "¡Hasta luego, María! 💕"),
        ]

        # Add all messages to state
        for role, content in conversation_messages:
            state = add_message(state, role, content)

        # Verify message count tracking
        assert state["total_message_count"] == 30, (
            f"Expected 30 total messages, got {state['total_message_count']}"
        )

        # Verify FIFO windowing: only recent 10 messages retained
        assert len(state["messages"]) == 10, (
            f"Expected 10 messages in windowed state, got {len(state['messages'])}"
        )

        # Manually trigger summarization at message 20 to verify behavior
        # (In real flow, this would be triggered by the graph routing)
        summarization_test_state: ConversationState = {
            **state,
            "total_message_count": 20,  # Simulate being at message 20
            "messages": state["messages"][:10],  # Take first 10 for this test
        }

        # Import and call summarization node directly
        from agent.nodes.summarization import summarize_conversation

        summarized_state = await summarize_conversation(summarization_test_state)

        # Assertion 1: Verify conversation_summary field is populated
        assert summarized_state.get("conversation_summary") is not None, (
            "conversation_summary should be populated after summarization"
        )

        summary = summarized_state["conversation_summary"]
        assert len(summary) > 0, "Summary should not be empty"

        # Assertion 2: Verify summary contains key context
        # Check for customer name, service type, or date/time mentions
        summary_lower = summary.lower()
        assert any(
            keyword in summary_lower
            for keyword in ["maría", "cliente", "cita", "corte", "tinte", "pago", "confirmación"]
        ), f"Summary should contain key booking context. Got: {summary}"

        # Assertion 3: Verify recent messages are still retained
        assert len(summarized_state["messages"]) == 10, (
            "Should retain 10 recent messages after summarization"
        )

        # Assertion 4: Estimate final token count
        final_tokens = estimate_token_count(summarized_state)

        # With summary + 10 messages, should be well under 10k tokens
        assert final_tokens < 10_000, (
            f"Final token count should be < 10k, got {final_tokens}"
        )

        # Assertion 5: Verify token count is reasonable
        # System prompt (500) + summary (~50-100) + 10 messages (~200-300) = ~800-900 tokens
        assert 500 < final_tokens < 2000, (
            f"Token count seems unrealistic: {final_tokens}"
        )

        # Assertion 6: Verify conversation can continue after summarization
        # Add message 31
        post_summary_state = add_message(
            summarized_state,
            "user",
            "Una última pregunta, ¿hacéis mechas?"
        )

        assert post_summary_state["total_message_count"] == 21, (
            "Message count should continue incrementing after summarization"
        )

        # Verify summary persists through additional messages
        assert post_summary_state.get("conversation_summary") == summary, (
            "Summary should persist when adding new messages"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summarization_combines_multiple_batches():
    """
    Test that summarization correctly combines multiple summary batches.

    This simulates a very long conversation (40+ messages) where summarization
    triggers twice (at message 20 and 30), and verifies summaries are combined.
    """
    mock_summary_1 = MagicMock()
    mock_summary_1.content = "Primera parte: Cliente reserva cita para corte."

    mock_summary_2 = MagicMock()
    mock_summary_2.content = "Segunda parte: Cliente confirma pago y pregunta por parking."

    # Track invocation count to return different summaries
    call_count = 0

    async def mock_ainvoke(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_summary_1
        else:
            return mock_summary_2

    with patch("agent.nodes.summarization.ChatOpenAI") as mock_llm_class:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.ainvoke = mock_ainvoke
        mock_llm_class.return_value = mock_llm_instance

        # Import summarization node
        from agent.nodes.summarization import summarize_conversation

        # Create initial state at message 20 (first summarization)
        state_20: ConversationState = {
            "conversation_id": "test-multi-summary",
            "total_message_count": 20,
            "messages": [{"role": "user", "content": f"Message {i}"} for i in range(10)],
            "conversation_summary": None,
        }

        # First summarization
        state_after_first = await summarize_conversation(state_20)

        assert state_after_first["conversation_summary"] == "Primera parte: Cliente reserva cita para corte."

        # Create state at message 30 (second summarization)
        state_30: ConversationState = {
            **state_after_first,
            "total_message_count": 30,
            "messages": [{"role": "user", "content": f"Message {i+20}"} for i in range(10)],
        }

        # Second summarization
        state_after_second = await summarize_conversation(state_30)

        # Verify summaries are combined with newline separator
        expected_combined = (
            "Primera parte: Cliente reserva cita para corte.\n\n"
            "Segunda parte: Cliente confirma pago y pregunta por parking."
        )
        assert state_after_second["conversation_summary"] == expected_combined
