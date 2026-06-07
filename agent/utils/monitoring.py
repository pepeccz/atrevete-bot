"""
Langfuse monitoring utilities for agent observability and token tracking.

This module provides helpers to integrate Langfuse tracing into the
conversational agent, enabling:
- Token usage monitoring and cost tracking
- Conversation flow tracing (nodes, tools, LLM calls)
- Performance metrics (latency, error rates)
- Customer behavior analytics (session/user grouping)

NOTE: Langfuse 4.x uses OpenTelemetry. Credentials (public_key, secret_key,
host) are configured once via env vars set at deploy time.  Per-call values
(session_id, user_id, tags) are passed through the ``propagate_attributes``
context manager — never via os.environ mutation, which would be a race
condition under concurrent workers.
"""

import logging

from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler

from shared.config import get_settings

logger = logging.getLogger(__name__)


def get_langfuse_client() -> Langfuse | None:
    """
    Create a Langfuse client for direct API calls (flush, scoring, etc).

    Returns:
        Langfuse: Configured Langfuse client instance, or None if not configured.
        The client uses the same environment variables as the callback handler.

    Example:
        >>> client = get_langfuse_client()
        >>> if client:
        ...     client.flush()  # Ensure traces are sent
    """
    settings = get_settings()

    # Return None if Langfuse is not configured
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return None

    try:
        client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_BASE_URL or None,
        )
        logger.debug("Langfuse client created successfully")
        return client
    except Exception as e:
        logger.warning(f"Failed to create Langfuse client: {e}")
        return None


def get_langfuse_handler(
    conversation_id: str,
    customer_phone: str,
    customer_name: str | None = None,
    additional_metadata: dict | None = None,
) -> tuple[CallbackHandler, object]:
    """
    Create a Langfuse callback handler for tracing agent conversations.

    Langfuse 4.x uses OpenTelemetry.  Per-call identifiers (session_id,
    user_id, tags) are scoped via ``propagate_attributes`` — a context
    manager that injects OTEL span attributes without touching os.environ.
    Credentials are read from env vars configured once at deploy time.

    Args:
        conversation_id: Chatwoot conversation ID — used as session_id
        customer_phone: Customer's phone number — used as user_id
        customer_name: Optional customer name for tag enrichment
        additional_metadata: Optional dict with extra metadata to attach

    Returns:
        Tuple of (CallbackHandler, propagate_attributes context manager).
        The caller MUST enter the context manager (``async with ctx:``) around
        the graph invocation so that all child spans inherit session/user/tags.

    Example:
        >>> handler, ctx = get_langfuse_handler(
        ...     conversation_id="wa-msg-123",
        ...     customer_phone="+34612345678",
        ...     customer_name="María García",
        ... )
        >>> config = {
        ...     "configurable": {"thread_id": conversation_id},
        ...     "callbacks": [handler],
        ... }
        >>> async with ctx:
        ...     result = await graph.ainvoke(state, config=config)
    """
    settings = get_settings()

    # Build per-call tags — no os.environ mutation
    tags = ["production", "whatsapp", "langgraph"]
    if customer_name:
        tags.append(f"customer:{customer_name}")

    # propagate_attributes scopes session_id / user_id / tags to OTEL context.
    # The caller wraps graph.ainvoke with this context manager so all child
    # spans inherit the attributes without any global-state side effects.
    ctx = propagate_attributes(
        session_id=conversation_id,
        user_id=customer_phone,
        tags=tags,
    )

    try:
        handler = CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY or None,
        )
        logger.debug(
            f"Langfuse handler created for conversation {conversation_id} "
            f"(customer: {customer_phone})"
        )
        return handler, ctx
    except Exception as e:
        logger.error(f"Failed to create Langfuse handler: {e}", exc_info=True)
        # Langfuse failures should not break the bot
        raise
