"""
Tests for _build_simple_dynamic_context display name behavior.

After the customer-name-handling refactor, customer names are NEVER injected
into prompt context. The LLM should not have access to customer names at all.
"""

from typing import Any, cast

import pytest

from agent.prompts.loader import _build_simple_dynamic_context
from agent.state.schemas import ConversationState


@pytest.mark.parametrize(
    "state",
    [
        {"customer_first_name": "Ana", "customer_name": "Maria", "pending_whatsapp_name": "Lola"},
        {"customer_first_name": None, "customer_name": "Maria", "pending_whatsapp_name": "Lola"},
        {"customer_first_name": None, "customer_name": None, "pending_whatsapp_name": "Lola"},
        {"customer_first_name": None, "customer_name": None, "pending_whatsapp_name": None},
    ],
)
def test_build_step_context_never_injects_customer_name(
    state: Any,
) -> None:
    """Customer name must NEVER appear in prompt context."""
    state_data: ConversationState = cast(ConversationState, state)
    context = _build_simple_dynamic_context(state_data, {})

    assert "Nombre del cliente" not in context
    # Also verify specific names don't leak
    for name in ("Ana", "Maria", "Lola"):
        if (
            state.get("customer_first_name") == name
            or state.get("customer_name") == name
            or state.get("pending_whatsapp_name") == name
        ):
            assert name not in context, f"Name '{name}' should not appear in prompt context"
