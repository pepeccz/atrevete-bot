"""
Message management helper functions for ConversationState.

This module provides utilities for managing conversation state in the
mode-based architecture (v6.0). Functions return partial state update dicts
compatible with LangGraph reducer semantics.

Key design:
- add_message() returns {"messages": [new_msg]} — reducer appends it
- increment_error_count() returns {"error_count": n+1}
- should_summarize() checks total_message_count threshold
- All helpers are pure functions (no mutation)
"""

import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

# Maximum character length for a single message (prevents token overflow)
MAX_MESSAGE_LENGTH = 2000

# Summarization trigger: every 10 messages after the first 10
SUMMARIZE_EVERY = 10
SUMMARIZE_MIN = 19


def add_message(
    state: ConversationState,
    role: Literal["user", "assistant"],
    content: str,
) -> dict:
    """
    Return a partial state update that appends a new message.

    Compatible with the append-only `messages` field reducer (operator.add).
    The returned dict contains only `{"messages": [new_message], ...metadata}`.
    LangGraph will merge it via the reducer — do NOT spread state here.

    Args:
        state: Current conversation state (read-only for metadata)
        role: Message role — "user" or "assistant"
        content: Message content text (truncated if > 2000 chars)

    Returns:
        Partial state update dict: {"messages": [new_message], "total_message_count": N}

    Example:
        >>> update = add_message(state, "user", "Hola")
        >>> # Return update from node; reducer appends the message to history
    """
    try:
        # Truncate message if too long (preserve first 800 and last 800 chars)
        truncated_content = content
        if len(content) > MAX_MESSAGE_LENGTH:
            conversation_id = state.get("conversation_id", "unknown")
            logger.warning(
                f"Message exceeds {MAX_MESSAGE_LENGTH} chars ({len(content)} chars), "
                f"truncating for conversation {conversation_id}"
            )
            truncated_content = (
                content[:800]
                + f"\n\n[... {len(content) - 1600} caracteres omitidos ...]\n\n"
                + content[-800:]
            )

        # Create new message dict with timestamp
        new_message = {
            "role": role,
            "content": truncated_content,
            "timestamp": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        }

        # Compute new total count (current count + 1)
        total_count = state.get("total_message_count", 0) + 1

        conversation_id = state.get("conversation_id", "unknown")
        logger.info(
            f"Adding {role} message to conversation {conversation_id}, "
            f"total_message_count will be: {total_count}"
        )

        # Return partial update — messages reducer will append the single-item list
        return {
            "messages": [new_message],
            "total_message_count": total_count,
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        }

    except Exception as e:
        logger.error(f"Error building add_message update: {e}", exc_info=True)
        # Return empty update on error — do not crash the node
        return {}


def should_summarize(state: ConversationState) -> bool:
    """
    Determine if conversation should be summarized based on message count.

    Summarization occurs after every 10 messages beyond the first 10.
    This is called AFTER the user message is counted but BEFORE the
    assistant response, so we trigger at 19, 29, 39... (odd numbers)
    so that after the assistant response the count is 20, 30, 40...

    Args:
        state: Current conversation state

    Returns:
        True if summarization should be triggered, False otherwise.

    Example:
        >>> state = {"total_message_count": 19}
        >>> should_summarize(state)
        True
        >>> state = {"total_message_count": 20}
        >>> should_summarize(state)
        False
    """
    total_message_count = state.get("total_message_count", 0)

    if total_message_count == 0:
        return False

    # Trigger at 19, 29, 39... (anticipates the upcoming assistant response)
    should_trigger = (
        (total_message_count + 1) % SUMMARIZE_EVERY == 0
        and total_message_count >= SUMMARIZE_MIN
    )

    if should_trigger:
        conversation_id = state.get("conversation_id", "unknown")
        logger.info(
            f"Summarization triggered at {total_message_count} messages "
            f"(will be {total_message_count + 1} after assistant response) "
            f"for conversation {conversation_id}"
        )

    return should_trigger


def increment_error_count(state: ConversationState) -> dict:
    """
    Return a partial state update that increments error_count by 1.

    Args:
        state: Current conversation state

    Returns:
        Partial state update dict: {"error_count": current + 1}

    Example:
        >>> update = increment_error_count(state)
        >>> # Merge returned dict into state
    """
    current_count = state.get("error_count", 0) or 0
    new_count = current_count + 1

    conversation_id = state.get("conversation_id", "unknown")
    logger.warning(
        f"Incrementing error_count to {new_count} for conversation {conversation_id}"
    )

    return {"error_count": new_count}


def estimate_token_count(state: ConversationState) -> int:
    """
    Estimate the total token count for the current conversation context.

    Uses a rough word-to-token ratio of 1.3 (average for English/Spanish text).

    Args:
        state: Current conversation state

    Returns:
        Estimated token count for the complete LLM context
    """
    # Fixed token count for system prompt (measured from actual prompt file)
    system_prompt_tokens = 500

    # Estimate summary tokens if present
    summary = state.get("conversation_summary", "")
    summary_tokens = 0
    if summary:
        summary_tokens = int(len(summary.split()) * 1.3)

    # Estimate recent messages tokens
    messages = state.get("messages", [])
    messages_tokens = 0
    for msg in messages:
        content = msg.get("content", "")
        messages_tokens += int(len(content.split()) * 1.3)

    return system_prompt_tokens + summary_tokens + messages_tokens


def check_token_overflow(state: ConversationState) -> dict[str, bool | str]:
    """
    Check if conversation context is approaching the LLM token limit.

    Args:
        state: Current conversation state

    Returns:
        {"overflow": False} or {"overflow": True, "action": "aggressive_summarize"|"escalate"}
    """
    CONTEXT_LIMIT = 200_000
    WARNING_THRESHOLD = int(CONTEXT_LIMIT * 0.70)   # 140,000 tokens
    CRITICAL_THRESHOLD = int(CONTEXT_LIMIT * 0.90)  # 180,000 tokens

    current_tokens = estimate_token_count(state)

    if current_tokens < WARNING_THRESHOLD:
        return {"overflow": False}

    conversation_id = state.get("conversation_id", "unknown")

    if current_tokens < CRITICAL_THRESHOLD:
        logger.warning(
            f"Token overflow warning for conversation {conversation_id}: "
            f"{current_tokens} tokens (threshold: {WARNING_THRESHOLD}). "
            f"Triggering aggressive summarization."
        )
        return {"overflow": True, "action": "aggressive_summarize"}

    logger.error(
        f"Critical token overflow for conversation {conversation_id}: "
        f"{current_tokens} tokens (critical: {CRITICAL_THRESHOLD}). Escalating."
    )
    return {"overflow": True, "action": "escalate"}


def format_llm_messages_with_summary(
    state: ConversationState, user_prompt: str
) -> list[dict[str, str]]:
    """
    Format messages for LLM invocation, including summary if present.

    Args:
        state: Current conversation state
        user_prompt: The user prompt to send to the LLM

    Returns:
        List of message dicts formatted for the LLM API.
    """
    summary = state.get("conversation_summary")

    if summary:
        combined_content = f"Contexto previo: {summary}\n\n{user_prompt}"
    else:
        combined_content = user_prompt

    return [{"role": "user", "content": combined_content}]
