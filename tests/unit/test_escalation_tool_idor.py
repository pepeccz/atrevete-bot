"""TDD tests: B1 IDOR fix — escalate tool must read customer_phone and conversation_id
from InjectedState (F2, quick-wins-bundle).

T6 (RED → GREEN): Write failing tests that confirm:
  - escalate reads customer_phone from state, not from LLM arg
  - escalate reads conversation_id from state (F2: removed from LLM-visible schema)
  - escalate rejects when state['customer_phone'] is missing
  - escalate rejects when state['conversation_id'] is missing
"""

from __future__ import annotations

import pytest

STATE_PHONE = "+34611000020"
CONVERSATION_ID = "conv-abc-123"


@pytest.mark.asyncio
async def test_escalation_ignores_llm_supplied_customer_phone():
    """B1: escalate reads customer_phone and conversation_id from InjectedState.

    When state['customer_phone'] = STATE_PHONE and state['conversation_id'] = CONVERSATION_ID,
    the tool must forward both to perform_escalation from state (not LLM args).
    """
    from unittest.mock import patch

    captured = {}

    async def fake_perform_escalation(**kwargs):
        captured["phone"] = kwargs.get("customer_phone")
        captured["conversation_id"] = kwargs.get("conversation_id")
        from agent.services.escalation_service import EscalationResult

        return EscalationResult(success=True, user_message="Transferido.")

    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        side_effect=fake_perform_escalation,
    ):
        from agent.tools.escalation_tools import escalate

        result = await escalate.coroutine(
            reason="customer request",
            state={
                "customer_phone": STATE_PHONE,
                "conversation_id": CONVERSATION_ID,
            },
        )

    assert captured.get("phone") == STATE_PHONE, (
        f"Expected state phone {STATE_PHONE} forwarded to perform_escalation, "
        f"got: {captured.get('phone')}"
    )
    assert captured.get("conversation_id") == CONVERSATION_ID, (
        f"Expected state conversation_id {CONVERSATION_ID} forwarded, "
        f"got: {captured.get('conversation_id')}"
    )
    assert "agente" in result.lower() or "transferido" in result.lower(), (
        f"Expected success message, got: {result!r}"
    )


@pytest.mark.asyncio
async def test_escalation_proceeds_when_state_customer_phone_missing():
    """AS7: escalate proceeds (does not abort) when state has no customer_phone.

    Updated per safety-and-correctness-bundle T1: empty phone guard removed so
    escalation works for conversations without a registered phone number.
    """
    from unittest.mock import patch

    from agent.services.escalation_service import EscalationResult

    mock_result = EscalationResult(success=True, user_message="Transferido.")
    called = []

    async def fake_perform_escalation(**kwargs):
        called.append(kwargs)
        return mock_result

    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        side_effect=fake_perform_escalation,
    ):
        from agent.tools.escalation_tools import escalate

        result = await escalate.coroutine(
            reason="customer request",
            state={"conversation_id": CONVERSATION_ID},  # no customer_phone
        )

    assert called, "perform_escalation must be called even when customer_phone is absent"
    assert isinstance(result, str) and len(result) > 0
