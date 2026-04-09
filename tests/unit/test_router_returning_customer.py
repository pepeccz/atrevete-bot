from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import router_node
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


@pytest.mark.asyncio
async def test_router_returning_customer_booking_intent_bypasses_greeting() -> None:
    state = create_initial_state("conv-router-returning", "+34600000002")
    state["current_mode"] = "GENERAL"
    state["customer_name"] = "Ana"
    state["customer_id"] = "2ebf8aaf-03ed-4b4b-a063-88db48cd67db"
    state["is_first_interaction"] = False  # Returning customer — not their first message ever
    state["messages"] = [
        {
            "role": "user",
            "content": "quiero reservar",
            "timestamp": "2026-03-17T10:00:00+01:00",
        }
    ]
    state["user_message"] = "quiero reservar"

    router = MagicMock()
    router.classify = AsyncMock(
        return_value=IntentResult(
            intent="book",
            confidence=0.95,
            raw_input="quiero reservar",
            mode_hint=None,
        )
    )

    with patch("agent.graphs.conversation_flow._get_intent_router", return_value=router):
        result = await router_node(state)

    assert result["current_mode"] == "BOOKING"
