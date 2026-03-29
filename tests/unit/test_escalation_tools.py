"""
Unit tests for escalation_tools.py - Human escalation functionality.

Tests coverage:
- escalate_to_human() tool with different call patterns
- New contract: {"escalated": bool, "duplicate_prevented": bool, "steps_completed": list}
- Missing context path: {"escalated": True, "error": "missing_context"}
- Schema validation
- Logging behavior
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.tools.escalation_tools import escalate_to_human, EscalateToHumanSchema
from agent.services.escalation_service import EscalationResult


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
# Helpers — build mocked EscalationResult
# ============================================================================


def _make_esc_result(
    success=True,
    duplicate_prevented=False,
    steps_completed=None,
    steps_failed=None,
    user_message="Con mucho gusto te paso con alguien del equipo. 🙏",
):
    return EscalationResult(
        success=success,
        duplicate_prevented=duplicate_prevented,
        steps_completed=steps_completed or ["disable_bot", "labels", "private_note", "db_record"],
        steps_failed=steps_failed or [],
        user_message=user_message,
    )


# ============================================================================
# Test new contract — ainvoke with context
# ============================================================================


class TestEscalationNewContract:
    """Validate the new return shape: {escalated, duplicate_prevented, steps_completed}.

    Note: The tool's injected params (_conversation_id, _customer_phone) are filtered
    by LangChain's args_schema. To test the full path including those params, we call
    escalate_to_human.coroutine() directly (the underlying async function).
    """

    @pytest.mark.asyncio
    async def test_result_has_escalated_key(self):
        """escalated key present and True on success."""
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=_make_esc_result(),
        ):
            result = await escalate_to_human.coroutine(
                reason="manual_request",
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
        assert result["escalated"] is True

    @pytest.mark.asyncio
    async def test_result_has_duplicate_prevented(self):
        """duplicate_prevented forwarded from EscalationResult."""
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=_make_esc_result(duplicate_prevented=True),
        ):
            result = await escalate_to_human.coroutine(
                reason="manual_request",
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
        assert result["duplicate_prevented"] is True

    @pytest.mark.asyncio
    async def test_result_has_steps_completed(self):
        """steps_completed forwarded from EscalationResult."""
        expected_steps = ["disable_bot", "labels"]
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=_make_esc_result(steps_completed=expected_steps),
        ):
            result = await escalate_to_human.coroutine(
                reason="manual_request",
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
        assert result["steps_completed"] == expected_steps

    @pytest.mark.asyncio
    async def test_no_reason_or_message_key(self):
        """Old contract keys 'reason' and 'message' should NOT be in result."""
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=_make_esc_result(),
        ):
            result = await escalate_to_human.coroutine(
                reason="ambiguity",
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
        assert "reason" not in result
        assert "message" not in result

    @pytest.mark.asyncio
    async def test_missing_context_returns_error_key(self):
        """When both context params are absent, returns {escalated: True, error: missing_context}."""
        result = await escalate_to_human.coroutine(reason="manual_request")
        assert result["escalated"] is True
        assert result["error"] == "missing_context"

    @pytest.mark.asyncio
    async def test_missing_phone_returns_error_key(self):
        """Missing phone returns missing_context error."""
        result = await escalate_to_human.coroutine(reason="manual_request", _conversation_id="123")
        assert result["escalated"] is True
        assert result["error"] == "missing_context"

    @pytest.mark.asyncio
    async def test_missing_conversation_id_returns_error_key(self):
        """Missing conversation_id returns missing_context error."""
        result = await escalate_to_human.coroutine(
            reason="manual_request", _customer_phone="+5491100000000"
        )
        assert result["escalated"] is True
        assert result["error"] == "missing_context"


# ============================================================================
# Test escalated reflects success field
# ============================================================================


class TestEscalatedReflectsSuccess:
    """escalated in result maps directly to result.success from EscalationResult."""

    @pytest.mark.asyncio
    async def test_success_true_maps_to_escalated_true(self):
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=_make_esc_result(success=True),
        ):
            result = await escalate_to_human.coroutine(
                reason="manual_request",
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
        assert result["escalated"] is True

    @pytest.mark.asyncio
    async def test_success_false_maps_to_escalated_false(self):
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=_make_esc_result(success=False),
        ):
            result = await escalate_to_human.coroutine(
                reason="technical_error",
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
        assert result["escalated"] is False


# ============================================================================
# Test all escalation reasons are forwarded correctly
# ============================================================================


class TestEscalationReasonRouting:
    """Verify all reasons are forwarded to perform_escalation."""

    @pytest.mark.asyncio
    async def test_reason_forwarded_to_service(self):
        """perform_escalation is called with the correct reason."""
        mock_perform = AsyncMock(return_value=_make_esc_result())
        with patch("agent.services.escalation_service.perform_escalation", mock_perform):
            await escalate_to_human.coroutine(
                reason="medical_consultation",
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
        call_kwargs = mock_perform.call_args.kwargs
        assert call_kwargs["reason"] == "medical_consultation"

    @pytest.mark.asyncio
    async def test_multiple_reasons_all_succeed(self):
        """All predefined reasons produce a valid result dict."""
        reasons = [
            "medical_consultation",
            "ambiguity",
            "manual_request",
            "technical_error",
            "auto_escalation",
        ]
        mock_perform = AsyncMock(return_value=_make_esc_result())
        with patch("agent.services.escalation_service.perform_escalation", mock_perform):
            for reason in reasons:
                result = await escalate_to_human.coroutine(
                    reason=reason,
                    _conversation_id="123",
                    _customer_phone="+5491100000000",
                )
                assert "escalated" in result, f"Missing 'escalated' for reason={reason}"
                assert "duplicate_prevented" in result, (
                    f"Missing 'duplicate_prevented' for reason={reason}"
                )
                assert "steps_completed" in result, f"Missing 'steps_completed' for reason={reason}"


# ============================================================================
# Test Logging Behavior
# ============================================================================


class TestLoggingBehavior:
    """Test that escalations are logged correctly."""

    @pytest.mark.asyncio
    async def test_missing_context_logs_warning(self):
        """Missing context logs a warning."""
        with patch("agent.tools.escalation_tools.logger") as mock_logger:
            await escalate_to_human.ainvoke({"reason": "medical_consultation"})

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0][0]
            assert "Missing" in call_args


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    @pytest.mark.asyncio
    async def test_empty_string_reason_missing_context(self):
        """Empty reason with no context returns missing_context."""
        result = await escalate_to_human.ainvoke({"reason": ""})
        assert result["escalated"] is True
        assert result["error"] == "missing_context"

    @pytest.mark.asyncio
    async def test_very_long_reason_forwarded(self):
        """Very long reason string is forwarded without error."""
        long_reason = "a" * 1000
        mock_perform = AsyncMock(return_value=_make_esc_result())
        with patch("agent.services.escalation_service.perform_escalation", mock_perform):
            result = await escalate_to_human.coroutine(
                reason=long_reason,
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
        assert result["escalated"] is True
        call_kwargs = mock_perform.call_args.kwargs
        assert call_kwargs["reason"] == long_reason

    @pytest.mark.asyncio
    async def test_multiple_calls_independent(self):
        """Multiple calls to the tool are independent."""
        mock_perform = AsyncMock(
            side_effect=[
                _make_esc_result(steps_completed=["disable_bot"]),
                _make_esc_result(steps_completed=["disable_bot", "labels"]),
            ]
        )
        with patch("agent.services.escalation_service.perform_escalation", mock_perform):
            result1 = await escalate_to_human.coroutine(
                reason="medical_consultation",
                _conversation_id="123",
                _customer_phone="+5491100000000",
            )
            result2 = await escalate_to_human.coroutine(
                reason="ambiguity",
                _conversation_id="456",
                _customer_phone="+5491100000001",
            )
        assert result1["steps_completed"] != result2["steps_completed"]
