"""Tests for escalate tool — InjectedState contract (AS3, AS4, AS4b).

F2: conversation_id must NOT be in the LLM-visible schema; it must be
    read from injected state, mirroring the existing customer_phone pattern.
"""

from __future__ import annotations

import pytest


class TestEscalateSchemaNoConversationId:
    """AS3 — LLM-visible schema does not expose conversation_id."""

    def test_conversation_id_absent_from_args_schema(self) -> None:
        """escalate.args_schema must not contain a conversation_id field."""
        from agent.tools.escalation_tools import escalate

        schema_fields = escalate.args_schema.model_fields
        assert "conversation_id" not in schema_fields, (
            f"conversation_id must NOT be in escalate schema (LLM would hallucinate it). "
            f"Found fields: {list(schema_fields)}"
        )

    def test_reason_present_in_args_schema(self) -> None:
        """reason must remain an LLM-visible arg."""
        from agent.tools.escalation_tools import escalate

        schema_fields = escalate.args_schema.model_fields
        assert "reason" in schema_fields, (
            f"reason must be in escalate schema. Found: {list(schema_fields)}"
        )


class TestEscalateReadsConversationIdFromState:
    """AS4 — Tool reads conversation_id from injected state at runtime."""

    @pytest.mark.asyncio
    async def test_escalate_uses_conversation_id_from_state(self) -> None:
        """When state has conversation_id, escalate calls perform_escalation with it."""
        from unittest.mock import AsyncMock, patch

        from agent.tools.escalation_tools import escalate

        mock_result = {"success": True}
        with patch(
            "agent.tools.escalation_tools.perform_escalation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_escalate:
            result = await escalate.coroutine(
                reason="customer angry",
                state={
                    "conversation_id": "abc-123",
                    "customer_phone": "+34600000001",
                },
            )

        mock_escalate.assert_called_once_with(
            conversation_id="abc-123",
            customer_phone="+34600000001",
            reason="customer angry",
        )
        assert "transferido" in result or "agente" in result

    @pytest.mark.asyncio
    async def test_escalate_missing_conversation_id_returns_error_string(self) -> None:
        """AS4b — Missing conversation_id returns explicit error string, no exception."""
        from agent.tools.escalation_tools import escalate

        result = await escalate.coroutine(
            reason="customer angry",
            state={"customer_phone": "+34600000001"},
        )

        assert isinstance(result, str), "Tool must return a string, not raise"
        assert len(result) > 0, "Error message must not be empty"

    @pytest.mark.asyncio
    async def test_escalate_none_conversation_id_returns_error_string(self) -> None:
        """AS4b variant — None conversation_id returns explicit error string."""
        from agent.tools.escalation_tools import escalate

        result = await escalate.coroutine(
            reason="test",
            state={"conversation_id": None, "customer_phone": "+34600000001"},
        )

        assert isinstance(result, str), "Tool must return a string, not raise"
        assert len(result) > 0, "Error message must not be empty"
