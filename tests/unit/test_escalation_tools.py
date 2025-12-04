"""
Unit tests for escalation_tools.py - Human escalation functionality.

Tests coverage:
- escalate_to_human() function with different reasons
- Predefined escalation reasons (medical, ambiguity, delay, manual, technical)
- Default escalation message fallback
- Return value structure validation
- Logging behavior
"""

import pytest
from unittest.mock import patch

from agent.tools.escalation_tools import escalate_to_human, EscalateToHumanSchema


# ============================================================================
# Test Schema Validation
# ============================================================================


class TestEscalateToHumanSchema:
    """Test Pydantic schema for escalate_to_human tool."""

    def test_schema_with_valid_reason(self):
        """Test schema validation with valid reason."""
        schema = EscalateToHumanSchema(reason="medical_consultation")

        assert schema.reason == "medical_consultation"

    def test_schema_requires_reason(self):
        """Test that reason field is required."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            EscalateToHumanSchema()


# ============================================================================
# Test Escalation with Predefined Reasons
# ============================================================================


class TestEscalationPredefinedReasons:
    """Test escalation with predefined reason messages."""

    @pytest.mark.asyncio
    async def test_escalate_medical_consultation(self):
        """Test escalation for medical consultation reason."""
        result = await escalate_to_human(reason="medical_consultation")

        assert result["escalated"] is True
        assert result["reason"] == "medical_consultation"
        assert "salud" in result["message"].lower()
        assert "💕" in result["message"]

    @pytest.mark.asyncio
    async def test_escalate_ambiguity(self):
        """Test escalation for ambiguity reason."""
        result = await escalate_to_human(reason="ambiguity")

        assert result["escalated"] is True
        assert result["reason"] == "ambiguity"
        assert "asegurarme" in result["message"].lower()
        assert "🌸" in result["message"]

    @pytest.mark.asyncio
    async def test_escalate_delay_notice(self):
        """Test escalation for delay notice reason."""
        result = await escalate_to_human(reason="delay_notice")

        assert result["escalated"] is True
        assert result["reason"] == "delay_notice"
        assert "notificaré" in result["message"].lower()
        assert "😊" in result["message"]

    @pytest.mark.asyncio
    async def test_escalate_manual_request(self):
        """Test escalation for manual user request."""
        result = await escalate_to_human(reason="manual_request")

        assert result["escalated"] is True
        assert result["reason"] == "manual_request"
        assert "claro" in result["message"].lower()
        assert "💕" in result["message"]

    @pytest.mark.asyncio
    async def test_escalate_technical_error(self):
        """Test escalation for technical error."""
        result = await escalate_to_human(reason="technical_error")

        assert result["escalated"] is True
        assert result["reason"] == "technical_error"
        assert "disculpa" in result["message"].lower()
        assert "problema" in result["message"].lower()
        assert "🌸" in result["message"]


# ============================================================================
# Test Default Escalation Message
# ============================================================================


class TestDefaultEscalationMessage:
    """Test escalation with unknown/custom reasons."""

    @pytest.mark.asyncio
    async def test_escalate_unknown_reason(self):
        """Test that unknown reason uses default message."""
        result = await escalate_to_human(reason="unknown_reason")

        assert result["escalated"] is True
        assert result["reason"] == "unknown_reason"
        assert result["message"] == "Te conecto con el equipo ahora mismo 💕"

    @pytest.mark.asyncio
    async def test_escalate_custom_reason(self):
        """Test escalation with custom reason."""
        result = await escalate_to_human(reason="custom_situation")

        assert result["escalated"] is True
        assert result["reason"] == "custom_situation"
        assert "equipo" in result["message"].lower()


# ============================================================================
# Test Return Value Structure
# ============================================================================


class TestReturnValueStructure:
    """Test that return value has correct structure."""

    @pytest.mark.asyncio
    async def test_return_value_has_required_keys(self):
        """Test that return dict has all required keys."""
        result = await escalate_to_human(reason="test")

        assert "escalated" in result
        assert "reason" in result
        assert "message" in result

    @pytest.mark.asyncio
    async def test_escalated_always_true(self):
        """Test that escalated flag is always True."""
        reasons = [
            "medical_consultation",
            "ambiguity",
            "delay_notice",
            "manual_request",
            "technical_error",
            "unknown_reason",
        ]

        for reason in reasons:
            result = await escalate_to_human(reason=reason)
            assert result["escalated"] is True, f"Failed for reason: {reason}"

    @pytest.mark.asyncio
    async def test_reason_preserved_in_return(self):
        """Test that reason is preserved in return value."""
        test_reason = "test_preservation"
        result = await escalate_to_human(reason=test_reason)

        assert result["reason"] == test_reason

    @pytest.mark.asyncio
    async def test_message_is_string(self):
        """Test that message is always a string."""
        result = await escalate_to_human(reason="test")

        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0


# ============================================================================
# Test Logging Behavior
# ============================================================================


class TestLoggingBehavior:
    """Test that escalations are logged correctly."""

    @pytest.mark.asyncio
    async def test_escalation_logs_warning(self):
        """Test that escalation logs a warning message."""
        with patch("agent.tools.escalation_tools.logger") as mock_logger:
            await escalate_to_human(reason="medical_consultation")

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0][0]
            assert "Escalating" in call_args
            assert "medical_consultation" in call_args

    @pytest.mark.asyncio
    async def test_logging_includes_reason(self):
        """Test that log message includes the reason."""
        with patch("agent.tools.escalation_tools.logger") as mock_logger:
            test_reason = "custom_test_reason"
            await escalate_to_human(reason=test_reason)

            call_args = mock_logger.warning.call_args[0][0]
            assert test_reason in call_args


# ============================================================================
# Test All Predefined Messages
# ============================================================================


class TestAllPredefinedMessages:
    """Test that all predefined messages are appropriate."""

    @pytest.mark.asyncio
    async def test_all_messages_have_emojis(self):
        """Test that all predefined messages include emojis."""
        reasons = [
            "medical_consultation",
            "ambiguity",
            "delay_notice",
            "manual_request",
            "technical_error",
        ]

        for reason in reasons:
            result = await escalate_to_human(reason=reason)
            message = result["message"]

            # Check for common emojis
            has_emoji = any(emoji in message for emoji in ["💕", "🌸", "😊"])
            assert has_emoji, f"Message for {reason} lacks emoji: {message}"

    @pytest.mark.asyncio
    async def test_all_messages_are_friendly(self):
        """Test that all messages are customer-friendly."""
        reasons = [
            "medical_consultation",
            "ambiguity",
            "delay_notice",
            "manual_request",
            "technical_error",
        ]

        # Messages should not contain technical jargon
        forbidden_words = ["error", "exception", "failed", "crash"]

        for reason in reasons:
            result = await escalate_to_human(reason=reason)
            message = result["message"].lower()

            # Check message length (should be reasonable)
            assert len(message) > 10, f"Message too short for {reason}"
            assert len(message) < 200, f"Message too long for {reason}"

    @pytest.mark.asyncio
    async def test_medical_consultation_message_mentions_health(self):
        """Test that medical consultation message mentions health/salud."""
        result = await escalate_to_human(reason="medical_consultation")

        assert "salud" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_technical_error_message_is_apologetic(self):
        """Test that technical error message is apologetic."""
        result = await escalate_to_human(reason="technical_error")

        message_lower = result["message"].lower()
        assert "disculpa" in message_lower or "perdón" in message_lower


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    @pytest.mark.asyncio
    async def test_empty_string_reason(self):
        """Test escalation with empty string reason."""
        result = await escalate_to_human(reason="")

        assert result["escalated"] is True
        assert result["reason"] == ""
        assert result["message"] == "Te conecto con el equipo ahora mismo 💕"

    @pytest.mark.asyncio
    async def test_very_long_reason(self):
        """Test escalation with very long reason."""
        long_reason = "a" * 1000
        result = await escalate_to_human(reason=long_reason)

        assert result["escalated"] is True
        assert result["reason"] == long_reason

    @pytest.mark.asyncio
    async def test_reason_with_special_characters(self):
        """Test escalation with special characters in reason."""
        special_reason = "test!@#$%^&*()"
        result = await escalate_to_human(reason=special_reason)

        assert result["escalated"] is True
        assert result["reason"] == special_reason

    @pytest.mark.asyncio
    async def test_multiple_escalations_independent(self):
        """Test that multiple escalations don't interfere."""
        result1 = await escalate_to_human(reason="medical_consultation")
        result2 = await escalate_to_human(reason="ambiguity")

        # Each should have its own message
        assert result1["message"] != result2["message"]
        assert "salud" in result1["message"].lower()
        assert "asegurarme" in result2["message"].lower()
