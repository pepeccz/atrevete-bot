"""Tests for escalate tool — InjectedState contract (AS3, AS4, AS4b).

F2: conversation_id must NOT be in the LLM-visible schema; it must be
    read from injected state, mirroring the existing customer_phone pattern.
"""

from __future__ import annotations

import pytest

from agent.services.escalation_service import EscalationResult


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

        mock_result = EscalationResult(success=True, steps_failed=[])
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
            source="auto_escalation",
            issue_summary="",
        )
        assert any(word in result for word in ("transferido", "transfiero", "agente", "equipo"))

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


class TestEscalateIssueSummaryForwarding:
    """F4 — issue_summary tool arg forwarded unchanged to perform_escalation (REQ-F4-1..4)."""

    @pytest.mark.asyncio
    async def test_escalate_forwards_issue_summary_to_perform_escalation(self) -> None:
        """A non-empty issue_summary arg must reach perform_escalation unchanged."""
        from unittest.mock import AsyncMock, patch

        from agent.tools.escalation_tools import escalate

        mock_result = EscalationResult(success=True, steps_failed=[])
        with patch(
            "agent.tools.escalation_tools.perform_escalation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_escalate:
            await escalate.coroutine(
                reason="ambiguity",
                issue_summary="Cliente pide evento de 6 personas fuera de catálogo",
                state={
                    "conversation_id": "abc-123",
                    "customer_phone": "+34600000001",
                },
            )

        mock_escalate.assert_called_once_with(
            conversation_id="abc-123",
            customer_phone="+34600000001",
            reason="ambiguity",
            source="ambiguity",
            issue_summary="Cliente pide evento de 6 personas fuera de catálogo",
        )

    @pytest.mark.asyncio
    async def test_escalate_without_issue_summary_preserves_current_behavior(self) -> None:
        """REQ-F4-4 regression: omitting issue_summary forwards '' without raising."""
        from unittest.mock import AsyncMock, patch

        from agent.tools.escalation_tools import escalate

        mock_result = EscalationResult(success=True, steps_failed=[])
        with patch(
            "agent.tools.escalation_tools.perform_escalation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_escalate:
            result = await escalate.coroutine(
                reason="manual_request",
                state={
                    "conversation_id": "abc-123",
                    "customer_phone": "+34600000001",
                },
            )

        mock_escalate.assert_called_once_with(
            conversation_id="abc-123",
            customer_phone="+34600000001",
            reason="manual_request",
            source="manual_request",
            issue_summary="",
        )
        assert isinstance(result, str)


class TestEscalateDocstringNegativeExample:
    """F3 — escalate docstring must name the 2-person/family case as non-escalating (REQ-F3-3)."""

    def test_escalate_docstring_contains_negative_family_example(self) -> None:
        """Docstring must contrast a small family booking (do NOT escalate) against
        a large-group/event request (DO escalate), mirroring R-44's positive example."""
        from agent.tools.escalation_tools import escalate

        docstring = escalate.coroutine.__doc__ or ""

        assert "R-44" in docstring, (
            "escalate docstring must reference R-44 (sequential multi-person flow) "
            "as the correct handling for small family bookings."
        )
        assert (
            "NOT" in docstring.upper() or "NO " in docstring
        ), "escalate docstring must explicitly state the family case must NOT escalate."
