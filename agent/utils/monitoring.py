"""
Langfuse monitoring utilities for agent observability and token tracking.

This module provides helpers to integrate Langfuse tracing into the
conversational agent, enabling:
- Token usage monitoring and cost tracking
- Conversation flow tracing (nodes, tools, LLM calls)
- Performance metrics (latency, error rates)
- Customer behavior analytics (session/user grouping)

NOTE: Langfuse 3.x uses OpenTelemetry and requires environment variables:
- LANGFUSE_PUBLIC_KEY
- LANGFUSE_SECRET_KEY
- LANGFUSE_HOST (optional, defaults to Langfuse cloud)
"""

import logging
import os
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

    In Langfuse 3.x, configuration is done via environment variables.
    This function ensures the environment variables are set before
    creating the handler.

    Args:
        conversation_id: Chatwoot conversation ID (used as session_id via env)
        customer_phone: Customer's phone number (used as user_id via env)
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

    # Langfuse 3.x uses environment variables for configuration
    # Set them before creating the handler
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
    if settings.LANGFUSE_BASE_URL:
        os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_BASE_URL

    # Set session and user context via environment (Langfuse 3.x approach)
    os.environ["LANGFUSE_SESSION_ID"] = conversation_id
    os.environ["LANGFUSE_USER_ID"] = customer_phone

    # Build metadata tags
    tags = ["production", "whatsapp", "langgraph"]
    if customer_name:
        tags.append(f"customer:{customer_name}")

    os.environ["LANGFUSE_TAGS"] = ",".join(tags)

    try:
        # In Langfuse 3.x, CallbackHandler reads from environment variables
        handler = CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,  # Still accepts public_key
        )
        logger.debug(
            f"Langfuse handler created for conversation {conversation_id} "
            f"(customer: {customer_phone})"
        )
        return handler
    except Exception as e:
        logger.error(f"Failed to create Langfuse handler: {e}", exc_info=True)
        # Langfuse failures should not break the bot
        raise
