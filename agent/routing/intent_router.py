"""
Intent Router - Routes intents to booking or non-booking handlers.

This module implements the routing logic that separates booking flows
(FSM-prescribed tools) from non-booking flows (LLM conversational).

Key decision: Does this intent affect booking progress?
- YES → BookingHandler (prescriptive)
- NO → NonBookingHandler (conversational)
"""

import logging
from typing import TYPE_CHECKING

from agent.fsm.models import Intent, IntentType

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

    from agent.fsm import BookingFSM
    from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


class IntentRouter:
    """
    Routes intents to appropriate handler based on intent type.

    Booking intents (affect FSM state) → BookingHandler (prescriptive)
    Non-booking intents (informational) → NonBookingHandler (conversational)
    """

    # Intents that affect booking flow state
    BOOKING_INTENTS = {
        IntentType.START_BOOKING,
        IntentType.SELECT_SERVICE,
        IntentType.CONFIRM_SERVICES,
        IntentType.SELECT_STYLIST,
        IntentType.CHECK_AVAILABILITY,  # Part of booking flow
        IntentType.SELECT_SLOT,
        IntentType.PROVIDE_CUSTOMER_DATA,
        IntentType.CONFIRM_BOOKING,
        IntentType.CANCEL_BOOKING,
    }

    # Intents that don't affect booking state
    NON_BOOKING_INTENTS = {
        IntentType.GREETING,
        IntentType.FAQ,
        IntentType.ESCALATE,
        IntentType.UNKNOWN,
        IntentType.UPDATE_NAME,  # Name update in IDLE state
        # Appointment confirmation intents (48h confirmation flow)
        IntentType.CONFIRM_APPOINTMENT,
        IntentType.DECLINE_APPOINTMENT,
        # Double confirmation intents (decline flow) - v3.5
        IntentType.CONFIRM_DECLINE,
        IntentType.ABORT_DECLINE,
    }

    @staticmethod
    async def route(
        intent: Intent,
        fsm: "BookingFSM",
        state: "ConversationState",
        llm: "ChatOpenAI",
    ) -> tuple[str, dict | None]:
        """
        Route intent to appropriate handler.

        Args:
            intent: Extracted user intent
            fsm: BookingFSM instance (contains state + collected_data)
            state: Conversation state
            llm: LLM client for response generation

        Returns:
            Tuple of (response_text, state_updates)
            - response_text: Assistant response text
            - state_updates: Dict of state fields to update (or None)
        """
        is_booking = intent.type in IntentRouter.BOOKING_INTENTS

        logger.info(
            f"Routing intent | type={intent.type.value} | "
            f"is_booking={is_booking} | fsm_state={fsm.state.value}"
        )

        if is_booking:
            # Prescriptive flow: FSM decides tools
            from agent.routing.booking_handler import BookingHandler

            handler = BookingHandler(fsm, state, llm)
            return await handler.handle(intent), None
        else:
            # Conversational flow: LLM handles with safe tools
            from agent.routing.non_booking_handler import NonBookingHandler

            handler = NonBookingHandler(state, llm, fsm)
            # NonBookingHandler returns (response, state_updates)
            return await handler.handle(intent)
