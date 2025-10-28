"""
Greeting node for LangGraph conversation flow.

This module implements the greet_customer node which sends a welcome message
to customers initiating conversation with the bot.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from agent.state.schemas import ConversationState

# Configure logger
logger = logging.getLogger(__name__)


async def greet_customer(state: ConversationState) -> dict[str, Any]:
    """
    Send greeting message to customer.

    This node is the entry point for the conversation flow in Story 1.5.
    It sends a static greeting message: "¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸"

    Args:
        state: Current conversation state

    Returns:
        Updated state with greeting message appended to messages list

    Note:
        This function follows the immutable state pattern - it returns a new dict
        rather than mutating the input state.
    """
    # Extract conversation_id for logging
    conversation_id = state.get("conversation_id", "unknown")

    # Create greeting message
    greeting = "¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸"

    # Append AI message to messages list (immutable pattern - don't mutate state)
    messages = state.get("messages", []).copy()
    messages.append({"role": "assistant", "content": greeting})

    # Update timestamp
    updated_at = datetime.now(UTC)

    # Log greeting sent
    logger.info(
        f"Greeting sent for conversation_id={conversation_id}",
        extra={
            "conversation_id": conversation_id,
            "customer_phone": state.get("customer_phone"),
            "node_name": "greet_customer",
        },
    )

    # Return updated state (immutable pattern - return new dict)
    return {
        **state,
        "messages": messages,
        "updated_at": updated_at,
        "last_node": "greet_customer",
    }
