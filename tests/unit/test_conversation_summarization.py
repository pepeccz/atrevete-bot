"""
Unit tests for conversation summarization functionality.

Tests cover:
- should_summarize trigger logic
- summarize_conversation node behavior
- Summary combination logic
- Token estimation and overflow protection
- Message count tracking
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.nodes.summarization import summarize_conversation
from agent.state.helpers import (
    add_message,
    should_summarize,
    estimate_token_count,
    check_token_overflow,
)
from agent.state.schemas import ConversationState


class TestShouldSummarize:
    """Tests for should_summarize function."""

    def test_triggers_at_20_messages(self):
        """Verify summarization triggers at 20 messages."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 20,
            "messages": [],
        }
        assert should_summarize(state) is True

    def test_triggers_at_30_messages(self):
        """Verify summarization triggers at 30 messages."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 30,
            "messages": [],
        }
        assert should_summarize(state) is True

    def test_does_not_trigger_at_10_messages(self):
        """Verify summarization does NOT trigger at 10 messages."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 10,
            "messages": [],
        }
        assert should_summarize(state) is False

    def test_does_not_trigger_at_15_messages(self):
        """Verify summarization does NOT trigger at 15 messages."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 15,
            "messages": [],
        }
        assert should_summarize(state) is False

    def test_does_not_trigger_at_25_messages(self):
        """Verify summarization does NOT trigger at 25 messages."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 25,
            "messages": [],
        }
        assert should_summarize(state) is False

    def test_handles_missing_total_message_count(self):
        """Verify backward compatibility when total_message_count is missing."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "messages": [],
        }
        assert should_summarize(state) is False


class TestAddMessageTracking:
    """Tests for total_message_count tracking in add_message."""

    def test_increments_total_message_count(self):
        """Verify add_message increments total_message_count."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "messages": [],
            "total_message_count": 0,
        }

        # Add 3 messages
        state = add_message(state, "user", "Hola")
        assert state["total_message_count"] == 1

        state = add_message(state, "assistant", "Hola, soy Maite")
        assert state["total_message_count"] == 2

        state = add_message(state, "user", "Necesito una cita")
        assert state["total_message_count"] == 3

    def test_total_count_persists_through_windowing(self):
        """Verify total_message_count tracks ALL messages, even when windowed."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "messages": [],
            "total_message_count": 0,
        }

        # Add 15 messages (more than MAX_MESSAGES=10)
        for i in range(15):
            role = "user" if i % 2 == 0 else "assistant"
            state = add_message(state, role, f"Message {i+1}")

        # Verify: Only 10 messages in state, but total_message_count is 15
        assert len(state["messages"]) == 10
        assert state["total_message_count"] == 15


class TestSummarizeConversation:
    """Tests for summarize_conversation node."""

    @pytest.mark.asyncio
    async def test_skips_summarization_when_not_needed(self):
        """Verify node returns unchanged state when should_summarize is False."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 15,  # Not a trigger point
            "messages": [{"role": "user", "content": "Hola"}],
        }

        result = await summarize_conversation(state)

        # State should be unchanged
        assert result == state

    @pytest.mark.asyncio
    async def test_creates_summary_when_triggered(self):
        """Verify node creates summary when should_summarize is True."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 20,
            "messages": [
                {"role": "user", "content": "Hola, necesito una cita"},
                {"role": "assistant", "content": "Claro, ¿para qué servicio?"},
            ],
            "conversation_summary": None,
        }

        # Mock Claude API response
        mock_response = MagicMock()
        mock_response.content = "Cliente solicita cita para corte de pelo."

        with patch("agent.nodes.summarization.ChatAnthropic") as mock_llm:
            mock_instance = AsyncMock()
            mock_instance.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm.return_value = mock_instance

            result = await summarize_conversation(state)

            # Verify summary was created
            assert result["conversation_summary"] == "Cliente solicita cita para corte de pelo."

    @pytest.mark.asyncio
    async def test_combines_with_existing_summary(self):
        """Verify new summary is combined with existing summary."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 30,  # Second summarization trigger
            "messages": [
                {"role": "user", "content": "¿Hay disponibilidad mañana?"},
                {"role": "assistant", "content": "Sí, a las 10am"},
            ],
            "conversation_summary": "Cliente solicita cita para corte de pelo.",
        }

        # Mock Claude API response
        mock_response = MagicMock()
        mock_response.content = "Cliente confirma cita para mañana 10am."

        with patch("agent.nodes.summarization.ChatAnthropic") as mock_llm:
            mock_instance = AsyncMock()
            mock_instance.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm.return_value = mock_instance

            result = await summarize_conversation(state)

            # Verify summaries are combined
            expected_summary = (
                "Cliente solicita cita para corte de pelo.\n\n"
                "Cliente confirma cita para mañana 10am."
            )
            assert result["conversation_summary"] == expected_summary

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_api_failure(self):
        """Verify node returns unchanged state if Claude API fails."""
        state: ConversationState = {
            "conversation_id": "test-001",
            "total_message_count": 20,
            "messages": [{"role": "user", "content": "Hola"}],
        }

        # Mock Claude API to raise exception
        with patch("agent.nodes.summarization.ChatAnthropic") as mock_llm:
            mock_instance = AsyncMock()
            mock_instance.ainvoke = AsyncMock(side_effect=Exception("API error"))
            mock_llm.return_value = mock_instance

            result = await summarize_conversation(state)

            # State should be unchanged (graceful degradation)
            assert result == state


class TestTokenEstimation:
    """Tests for token estimation and overflow protection."""

    def test_estimate_token_count_basic(self):
        """Verify token estimation with summary and messages."""
        state: ConversationState = {
            "conversation_summary": "Cliente quiere corte de pelo.",  # ~6 words
            "messages": [
                {"role": "user", "content": "Hola necesito una cita"},  # ~4 words
                {"role": "assistant", "content": "Claro puedo ayudarte"},  # ~3 words
            ],
        }

        estimated_tokens = estimate_token_count(state)

        # System prompt: 500 tokens
        # Summary: ~6 * 1.3 = 7.8 tokens
        # Messages: ~7 * 1.3 = 9.1 tokens
        # Total: ~517 tokens (allow margin for rounding)
        assert 510 <= estimated_tokens <= 525

    def test_estimate_token_count_without_summary(self):
        """Verify token estimation without summary."""
        state: ConversationState = {
            "messages": [
                {"role": "user", "content": "Hola"},  # ~1 word
            ],
        }

        estimated_tokens = estimate_token_count(state)

        # System prompt: 500 tokens
        # Messages: ~1 * 1.3 = 1.3 tokens
        # Total: ~501 tokens
        assert 500 <= estimated_tokens <= 510

    def test_check_token_overflow_no_overflow(self):
        """Verify no overflow for normal conversations."""
        state: ConversationState = {
            "conversation_summary": "Short summary.",
            "messages": [{"role": "user", "content": "Hola"}],
        }

        result = check_token_overflow(state)

        assert result["overflow"] is False

    def test_check_token_overflow_warning_threshold(self):
        """Verify aggressive summarization triggered at 70% threshold."""
        # Create a state with ~150k tokens (above 140k warning threshold)
        large_summary = " ".join(["word"] * 115000)  # ~115k words * 1.3 = ~150k tokens

        state: ConversationState = {
            "conversation_id": "test-overflow",
            "conversation_summary": large_summary,
            "messages": [],
        }

        result = check_token_overflow(state)

        assert result["overflow"] is True
        assert result["action"] == "aggressive_summarize"

    def test_check_token_overflow_critical_threshold(self):
        """Verify escalation triggered at 90% threshold."""
        # Create a state with ~185k tokens (above 180k critical threshold)
        huge_summary = " ".join(["word"] * 142000)  # ~142k words * 1.3 = ~185k tokens

        state: ConversationState = {
            "conversation_id": "test-critical",
            "conversation_summary": huge_summary,
            "messages": [],
        }

        result = check_token_overflow(state)

        assert result["overflow"] is True
        assert result["action"] == "escalate"
