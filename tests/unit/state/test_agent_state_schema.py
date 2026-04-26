"""T8.c — sentinel: AgentState TypedDict fields match design baseline.

R-IDs: R16
"""
from __future__ import annotations

from agent.state import AgentState

# Frozen baseline: fields present at HEAD of feat/booking-tool-contract-rework.
# Any new field added → this test fails immediately, prompting a design review.
BASELINE_FIELDS = frozenset(
    {
        "conversation_id",
        "customer_phone",
        "user_message",
        "pending_whatsapp_name",
        "messages",
        "customer_id",
        "customer_name",
    }
)


def test_agent_state_fields() -> None:
    actual = frozenset(AgentState.__annotations__)
    assert actual == BASELINE_FIELDS, (
        f"AgentState fields changed — design review required.\n"
        f"Added:   {actual - BASELINE_FIELDS}\n"
        f"Removed: {BASELINE_FIELDS - actual}"
    )
