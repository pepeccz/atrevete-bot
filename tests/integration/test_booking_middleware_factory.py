"""Regression guardrail: BookingGroundingMiddleware and BookingInvariantMiddleware
must inherit from AgentMiddleware and plug into create_agent without errors.

R13 — This test MUST fail on the pre-fix codebase (confirmed by the tasks doc)
because the booking middlewares lack AgentMiddleware inheritance.

Phase A (A1) — RED: confirms classes lack AgentMiddleware.
Phase B (B3) — GREEN after inheritance added.
Phase F (F1, F2) — smoke ainvoke added.
"""

from __future__ import annotations

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from agent.booking.middleware.grounding import BookingGroundingMiddleware
from agent.booking.middleware.invariants import BookingInvariantMiddleware
from agent.middleware.dedup import DedupToolCallMiddleware
from agent.middleware.final_text_recovery import FinalTextRecoveryMiddleware
from agent.middleware.token_tracking import TokenTrackingMiddleware


def _make_booking_state(**overrides) -> dict:
    """Return a minimal BOOKING-mode state for smoke tests."""
    base = {
        "messages": [],
        "current_mode": "BOOKING",
        "conversation_id": "smoke",
        "booking_context": {
            "_booking_completed": False,
            "confirmed": False,
            "_confirmation_shown": False,
            "pending_disambiguations": [],
            "last_services": [],
            "add_more_asked": False,
            "last_stylist": None,
            "no_preference_stylist": False,
            "stylist_id": None,
            "offered_slots": None,
            "selected_slot": None,
            "customer_name": None,
            "notes_state": "not_asked",
        },
        "total_message_count": 0,
    }
    base.update(overrides)
    return base


class TestBookingMiddlewareFactory:
    """R13 — booking middleware stack can be composed with create_agent."""

    def _make_middleware_list(self, state_ref: dict) -> list:
        """Build the standard booking middleware list."""
        return [
            BookingGroundingMiddleware(
                get_state_fn=lambda: state_ref,
                mode_name="BOOKING",
            ),
            BookingInvariantMiddleware(
                get_state_fn=lambda: state_ref,
                get_catalog_fn=lambda: [],
                mode_name="BOOKING",
            ),
            DedupToolCallMiddleware(),
            FinalTextRecoveryMiddleware(fallback_text="Lo siento, no pude procesar tu solicitud."),
            TokenTrackingMiddleware(mode_name="BOOKING"),
        ]

    def test_booking_middleware_stack_construction_parity(self) -> None:
        """R3, R13 — create_agent must accept the full booking middleware stack without raising.

        RED on pre-fix code: AttributeError or TypeError because classes lack AgentMiddleware.
        GREEN after Phase B adds inheritance.
        """
        state_ref = _make_booking_state()
        middleware = self._make_middleware_list(state_ref)

        # AC4 / AC5 — both classes must be AgentMiddleware instances
        grounding = middleware[0]
        invariant = middleware[1]
        assert isinstance(grounding, AgentMiddleware), (
            f"BookingGroundingMiddleware is not an AgentMiddleware instance — "
            f"class lacks inheritance: {type(grounding).__mro__}"
        )
        assert isinstance(invariant, AgentMiddleware), (
            f"BookingInvariantMiddleware is not an AgentMiddleware instance — "
            f"class lacks inheritance: {type(invariant).__mro__}"
        )

        # create_agent must not raise
        fake_llm = FakeListChatModel(responses=["Hola, ¿en qué te puedo ayudar?"])
        agent = create_agent(model=fake_llm, tools=[], middleware=middleware)
        assert agent is not None

    @pytest.mark.asyncio
    async def test_booking_stack_ainvoke_one_turn_happy_path(self) -> None:
        """R13, AC2 — ainvoke must complete one turn without raising.

        GREEN after Phase C adds before_model hook.

        Note: before_model injects the grounding message EPHEMERALLY into the model call
        context — it is not persisted in the final state returned by ainvoke. The assertion
        here is that the agent completed successfully (result is not None and contains an
        AI response), which is the contract R13 requires.
        """
        state_ref = _make_booking_state()
        middleware = self._make_middleware_list(state_ref)

        fake_llm = FakeListChatModel(responses=["¿Qué servicio deseás reservar?"])
        agent = create_agent(model=fake_llm, tools=[], middleware=middleware)

        initial_state = _make_booking_state(
            messages=[HumanMessage(content="hola quiero un turno")],
            conversation_id="smoke",
            total_message_count=1,
        )

        result = await agent.ainvoke(initial_state)
        assert result is not None, "ainvoke must return a result"

        # Verify the AI response is present in the output messages
        messages = result.get("messages", [])
        ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
        assert len(ai_msgs) >= 1, (
            f"Expected at least 1 AIMessage in result, got message types: "
            f"{[type(m).__name__ for m in messages]}"
        )
