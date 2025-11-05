"""
Langfuse monitoring utilities for agent observability and token tracking.

This module provides helpers to integrate Langfuse tracing into the
conversational agent, enabling:
- Token usage monitoring and cost tracking
- Conversation flow tracing (nodes, tools, LLM calls)
- Performance metrics (latency, error rates)
- Customer behavior analytics (session/user grouping)
"""

import logging
from typing import Optional

from langfuse.langchain import CallbackHandler

from shared.config import get_settings

logger = logging.getLogger(__name__)


def get_langfuse_handler(
    conversation_id: str,
    customer_phone: str,
    customer_name: Optional[str] = None,
    additional_metadata: Optional[dict] = None,
) -> CallbackHandler:
    """
    Create a Langfuse callback handler for tracing agent conversations.

    This handler captures all LLM invocations, tool calls, and state transitions
    within a LangGraph conversation flow, grouping traces by:
    - session_id: WhatsApp conversation ID (groups messages in one conversation)
    - user_id: Customer phone number (groups all conversations for a customer)

    Args:
        conversation_id: Chatwoot conversation ID (used as Langfuse session_id)
        customer_phone: Customer's phone number (used as Langfuse user_id)
        customer_name: Optional customer name for metadata enrichment
        additional_metadata: Optional dict with extra metadata to attach

    Returns:
        CallbackHandler: Configured Langfuse callback handler

    Example:
        >>> handler = get_langfuse_handler(
        ...     conversation_id="wa-msg-123",
        ...     customer_phone="+34612345678",
        ...     customer_name="María García"
        ... )
        >>> config = {
        ...     "configurable": {"thread_id": conversation_id},
        ...     "callbacks": [handler]
        ... }
        >>> result = await graph.ainvoke(state, config=config)
        >>> await handler.flushAsync()  # Ensure traces are sent
    """
    settings = get_settings()

    # Build metadata
    metadata = {
        "customer_phone": customer_phone,
        "environment": settings.LOG_LEVEL,
        "timezone": settings.TIMEZONE,
    }

    if customer_name:
        metadata["customer_name"] = customer_name

    if additional_metadata:
        metadata.update(additional_metadata)

    try:
        handler = CallbackHandler(
            publicKey=settings.LANGFUSE_PUBLIC_KEY,
            secretKey=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_BASE_URL,
            sessionId=conversation_id,  # Group by conversation
            userId=customer_phone,  # Group by customer
            tags=["production", "whatsapp", "langgraph"],
            metadata=metadata,
        )
        logger.debug(
            f"Langfuse handler created for conversation {conversation_id} "
            f"(customer: {customer_phone})"
        )
        return handler
    except Exception as e:
        logger.error(f"Failed to create Langfuse handler: {e}", exc_info=True)
        # Return a no-op handler to ensure graceful degradation
        # (Langfuse failures should not break the bot)
        raise
