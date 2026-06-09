"""TDD tests: B1 IDOR fix — escalate tool must read customer_phone from InjectedState.

T6 (RED): Write failing tests that confirm:
  - escalate reads customer_phone from state, not from LLM arg
  - escalate rejects when state['customer_phone'] is missing
"""

from __future__ import annotations

import pytest

STATE_PHONE = "+34611000020"
CONVERSATION_ID = "conv-abc-123"


@pytest.mark.asyncio
async def test_escalation_ignores_llm_supplied_customer_phone():
    """B1: escalate reads customer_phone from InjectedState, not from LLM arg.

    When state['customer_phone'] = STATE_PHONE, the tool must forward STATE_PHONE
    to perform_escalation, not any LLM-supplied phone.
    """
    from unittest.mock import AsyncMock, patch

    captured = {}

    async def fake_perform_escalation(conversation_id, customer_phone, reason):
        captured["phone"] = customer_phone
        captured["conversation_id"] = conversation_id
        return {"success": True}

    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        side_effect=fake_perform_escalation,
    ):
        from agent.tools.escalation_tools import escalate

        result = await escalate.coroutine(
            reason="customer request",
            conversation_id=CONVERSATION_ID,
            state={"customer_phone": STATE_PHONE},
        )

    assert captured.get("phone") == STATE_PHONE, (
        f"Expected state phone {STATE_PHONE} forwarded to perform_escalation, "
        f"got: {captured.get('phone')}"
    )
    assert "agente" in result.lower() or "transferido" in result.lower(), (
        f"Expected success message, got: {result!r}"
    )


@pytest.mark.asyncio
async def test_escalation_rejects_when_state_customer_phone_missing():
    """B1: escalate rejects when state has no customer_phone."""
    from agent.tools.escalation_tools import escalate

    result = await escalate.coroutine(
        reason="customer request",
        conversation_id=CONVERSATION_ID,
        state={},  # no customer_phone
    )

    assert isinstance(result, str)
    assert len(result) > 0
    # Must return an error / rejection — not proceed with an empty phone
    assert (
        "incompleto" in result.lower()
        or "error" in result.lower()
        or "rejected" in result.lower()
    ), f"Expected rejection when state phone missing, got: {result!r}"
