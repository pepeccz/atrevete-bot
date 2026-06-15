"""T8.c — sentinel: AgentState TypedDict fields match design baseline.

R-IDs: R16

Updated baseline: quick-wins-bundle added _slot_appointment_management (F6).
"""
from __future__ import annotations

from agent.state import AgentState

# Frozen baseline: fields present after quick-wins-bundle (F6 adds _slot_appointment_management).
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
        # NotRequired fields added post-rework:
        "conversation_summary",
        "last_summarized_msg_count",
        "customer_memories",
        # Slot fields (7 total after quick-wins-bundle F6):
        "_slot_today",
        "_slot_customer",
        "_slot_upcoming_appointments",
        "_slot_appointment_management",
        "_slot_business_hours",
        "_slot_availability",
        "_slot_catalog",
        # Added by availability context middleware (next-slot offer tracking):
        "recently_offered_slots",
    }
)


def test_agent_state_fields() -> None:
    actual = frozenset(AgentState.__annotations__)
    assert actual == BASELINE_FIELDS, (
        f"AgentState fields changed — design review required.\n"
        f"Added:   {actual - BASELINE_FIELDS}\n"
        f"Removed: {BASELINE_FIELDS - actual}"
    )
