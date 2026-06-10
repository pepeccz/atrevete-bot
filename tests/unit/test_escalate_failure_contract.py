"""Change N (N2) — escalate tool loud-failure contract.

V6 audit C2: on EscalationResult.success=False the tool returned a soft
"Estoy intentando transferirte…" string, the LLM paraphrased it as success,
and the bot entered a phantom post-escalation lock with zero DB evidence.

Contract under test:
- success=False → machine-readable ESCALATION_FAILED payload; the LLM must
  not claim the handoff happened and must NOT tell the customer to call the
  salon (they are already in the salon's official channel).
- success=True → unchanged success message (the stop-responding lock applies
  only here).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.services.escalation_service import EscalationResult
from agent.tools.escalation_tools import escalate

STATE = {"conversation_id": "conv-1", "customer_phone": "+34999000023"}


@pytest.mark.asyncio
async def test_failure_returns_escalation_failed_marker():
    """success=False → result must carry the ESCALATION_FAILED marker."""
    failed = EscalationResult(success=False, steps_failed=["db_record"])
    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        new_callable=AsyncMock,
        return_value=failed,
    ):
        result = await escalate.ainvoke({"reason": "manual_request", "state": STATE})

    assert "ESCALATION_FAILED" in result, (
        "Failed escalation must return a machine-readable failure marker "
        "so the LLM cannot claim the handoff happened"
    )


@pytest.mark.asyncio
async def test_failure_does_not_tell_customer_to_call():
    """Failure path must never refer the customer to phone the salon."""
    failed = EscalationResult(success=False, steps_failed=["db_record"])
    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        new_callable=AsyncMock,
        return_value=failed,
    ):
        result = await escalate.ainvoke({"reason": "manual_request", "state": STATE})

    lowered = result.lower()
    assert "llámanos" not in lowered and "llamar" not in lowered, (
        "Never tell the customer to phone the salon — they are already in "
        "the salon's official channel"
    )


@pytest.mark.asyncio
async def test_exception_path_also_returns_failed_marker():
    """perform_escalation raising must also produce ESCALATION_FAILED, no call referral."""
    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        result = await escalate.ainvoke({"reason": "manual_request", "state": STATE})

    assert "ESCALATION_FAILED" in result
    assert "llámanos" not in result.lower()


@pytest.mark.asyncio
async def test_success_path_unchanged():
    """success=True keeps the user-facing success message (lock applies here only)."""
    ok = EscalationResult(success=True, user_message="Te paso con el equipo. 🙏")
    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        new_callable=AsyncMock,
        return_value=ok,
    ):
        result = await escalate.ainvoke({"reason": "manual_request", "state": STATE})

    assert "ESCALATION_FAILED" not in result
    assert "equipo" in result
