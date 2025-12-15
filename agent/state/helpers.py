"""
Message management helper functions for ConversationState.

This module provides utilities for managing message windowing in the conversation
state, implementing FIFO (First In First Out) windowing to maintain a maximum of
10 recent messages for LLM context management.
"""

import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

# Maximum number of messages to retain in state (10 exchanges = 10 user or assistant messages)
MAX_MESSAGES = 10

# Maximum character length for a single message (prevents token overflow)
MAX_MESSAGE_LENGTH = 2000


def add_message(
    state: ConversationState,
    role: Literal["user", "assistant"],
    content: str
) -> ConversationState:
    """
    Add a message to the conversation state with FIFO windowing and length limits.

    This function immutably adds a new message to the conversation state while:
    1. Maintaining a maximum of 10 recent messages (FIFO windowing)
    2. Truncating messages longer than 2000 characters with warning
    3. Tracking total message count for summarization triggers

    Args:
        state: Current conversation state
        role: Message role - either "user" or "assistant"
        content: Message content text (will be truncated if > 2000 chars)

    Returns:
        New ConversationState with updated messages list and updated_at timestamp.
        Original state dict is never mutated (immutability requirement).

    Example:
        >>> state = {"conversation_id": "abc", "messages": []}
        >>> state = add_message(state, "user", "Hola")
        >>> len(state["messages"])
        1
        >>> state["messages"][0]["content"]
        'Hola'
    """
    try:
        # Extract current messages list (default to empty list if missing)
        # Create a copy to avoid mutating the original state
        messages = list(state.get("messages", []))

        # Truncate message if too long (preserve first 800 and last 800 chars)
        truncated_content = content
        if len(content) > MAX_MESSAGE_LENGTH:
            conversation_id = state.get("conversation_id", "unknown")
            logger.warning(
                f"Message exceeds {MAX_MESSAGE_LENGTH} chars ({len(content)} chars), "
                f"truncating for conversation {conversation_id}"
            )
            # Preserve beginning and end of message
            truncated_content = (
                content[:800] +
                f"\n\n[... {len(content) - 1600} caracteres omitidos ...]\n\n" +
                content[-800:]
            )

        # Create new message dict with timestamp
        new_message = {
            "role": role,
            "content": truncated_content,
            "timestamp": datetime.now(ZoneInfo("Europe/Madrid")).isoformat()
        }

        # Append new message to messages list
        messages.append(new_message)

        # Apply FIFO windowing: keep only last 10 messages
        if len(messages) > MAX_MESSAGES:
            messages = messages[-MAX_MESSAGES:]

        # Track total message count (includes messages removed by windowing)
        total_count = state.get("total_message_count", 0) + 1

        # Log message addition for traceability
        conversation_id = state.get("conversation_id", "unknown")
        logger.info(
            f"Added {role} message to conversation {conversation_id}, "
            f"windowed messages: {len(messages)}, total_message_count: {total_count}"
        )

        # Return new state dict with updated messages (immutable pattern)
        return {
            **state,
            "messages": messages,
            "total_message_count": total_count,
            "updated_at": datetime.now(ZoneInfo("Europe/Madrid"))
        }

    except Exception as e:
        # Graceful degradation: return unchanged state on error
        logger.error(f"Error adding message: {e}", exc_info=True)
        return state


def should_summarize(state: ConversationState) -> bool:
    """
    Determine if conversation should be summarized based on message count.

    This function checks if summarization should be triggered. Summarization
    occurs after every 10 messages beyond the first 10 messages to compress
    older messages and maintain manageable context size.

    IMPORTANT: This function is called from route_entry() AFTER the user message
    is added but BEFORE the assistant response is added. Since each interaction
    adds 2 messages (user + assistant), we trigger when count is 19, 29, 39...
    (odd numbers) so that after the assistant response, the count will be 20, 30, 40...

    Args:
        state: Current conversation state

    Returns:
        True if summarization should be triggered, False otherwise.

    Logic:
        - Returns True if (total_message_count + 1) % 10 == 0 AND count >= 19
        - This triggers at counts 19, 29, 39... (before assistant makes it 20, 30, 40...)
        - Returns False if total_message_count field is missing (backwards compatibility)

    Example:
        >>> state = {"total_message_count": 19}
        >>> should_summarize(state)
        True
        >>> state = {"total_message_count": 20}
        >>> should_summarize(state)
        False
    """
    # Get total message count from state (default to 0 if missing)
    total_message_count = state.get("total_message_count", 0)

    # Return False if field missing (backwards compatibility)
    if total_message_count == 0:
        return False

    # Trigger summarization when count is 19, 29, 39, etc.
    # This anticipates the assistant response that will make it 20, 30, 40...
    # The +1 accounts for the upcoming assistant message
    should_trigger = ((total_message_count + 1) % 10 == 0 and total_message_count >= 19)

    if should_trigger:
        conversation_id = state.get("conversation_id", "unknown")
        logger.info(
            f"Summarization triggered at {total_message_count} messages "
            f"(will be {total_message_count + 1} after assistant response) "
            f"for conversation {conversation_id}"
        )

    return should_trigger


def estimate_token_count(state: ConversationState) -> int:
    """
    Estimate the total token count for the current conversation context.

    This function provides a rough estimation of how many tokens will be consumed
    when sending the conversation context to Claude. The estimation uses a simple
    word-to-token ratio of 1.3 (average for English/Spanish text).

    Args:
        state: Current conversation state

    Returns:
        Estimated token count for the complete LLM context

    Token Estimation Formula:
        - System prompt: ~500 tokens (fixed, measured from maite_system_prompt.md)
        - Summary: len(summary.split()) * 1.3 (rough word-to-token approximation)
        - Recent messages: sum(len(msg["content"].split()) * 1.3 for msg in messages)
        - Total = sum of above components

    Example:
        >>> state = {
        ...     "conversation_summary": "Cliente quiere corte de pelo.",
        ...     "messages": [{"content": "Hola, necesito una cita"}]
        ... }
        >>> estimate_token_count(state)
        520  # Approximate: 500 (system) + 6 (summary) + 14 (messages)
    """
    # Fixed token count for system prompt (measured from actual prompt file)
    system_prompt_tokens = 500

    # Estimate summary tokens if present
    summary = state.get("conversation_summary", "")
    summary_tokens = 0
    if summary:
        # Rough estimation: 1 word ≈ 1.3 tokens
        summary_tokens = int(len(summary.split()) * 1.3)

    # Estimate recent messages tokens
    messages = state.get("messages", [])
    messages_tokens = 0
    for msg in messages:
        content = msg.get("content", "")
        messages_tokens += int(len(content.split()) * 1.3)

    total_estimate = system_prompt_tokens + summary_tokens + messages_tokens

    return total_estimate


def check_token_overflow(state: ConversationState) -> dict[str, bool | str]:
    """
    Check if conversation context is approaching Claude's token limit.

    This function monitors token usage and triggers warnings or actions when
    the context size exceeds 70% of Claude Sonnet 4's 200k token limit (140k tokens).

    Args:
        state: Current conversation state

    Returns:
        Dictionary with overflow status and recommended action:
        - {"overflow": False} if below 70% threshold
        - {"overflow": True, "action": "aggressive_summarize"} if >70% but <90%
        - {"overflow": True, "action": "escalate"} if >90% (180k tokens)

    Actions:
        - "aggressive_summarize": Reduce recent messages from 10 → 5
        - "escalate": Conversation too complex, flag for human takeover

    Example:
        >>> state = {"conversation_summary": "..." * 50000}  # Very long summary
        >>> result = check_token_overflow(state)
        >>> result["overflow"]
        True
        >>> result["action"]
        'aggressive_summarize'
    """
    # Claude Sonnet 4 context limit: 200,000 tokens
    CONTEXT_LIMIT = 200_000
    WARNING_THRESHOLD = int(CONTEXT_LIMIT * 0.70)  # 140,000 tokens (70%)
    CRITICAL_THRESHOLD = int(CONTEXT_LIMIT * 0.90)  # 180,000 tokens (90%)

    # Get current token estimate
    current_tokens = estimate_token_count(state)

    # No overflow - conversation within safe limits
    if current_tokens < WARNING_THRESHOLD:
        return {"overflow": False}

    # Warning threshold exceeded - trigger aggressive summarization
    if current_tokens < CRITICAL_THRESHOLD:
        conversation_id = state.get("conversation_id", "unknown")
        logger.warning(
            f"Token overflow warning for conversation {conversation_id}: "
            f"{current_tokens} tokens (threshold: {WARNING_THRESHOLD}). "
            f"Triggering aggressive summarization."
        )
        return {"overflow": True, "action": "aggressive_summarize"}

    # Critical threshold exceeded - escalate to human
    conversation_id = state.get("conversation_id", "unknown")
    logger.error(
        f"Critical token overflow for conversation {conversation_id}: "
        f"{current_tokens} tokens (critical threshold: {CRITICAL_THRESHOLD}). "
        f"Escalating to human operator."
    )
    return {"overflow": True, "action": "escalate"}


def format_llm_messages_with_summary(state: ConversationState, user_prompt: str) -> list[dict[str, str]]:
    """
    Format messages for LLM invocation, including conversation summary if present.

    This helper prepares the message list for Claude API calls, ensuring that
    both the conversation summary (if exists) and the user prompt are included
    in the proper format.

    Args:
        state: Current conversation state
        user_prompt: The user prompt to send to Claude

    Returns:
        List of message dicts formatted for Claude API with roles and content.
        Format: [{"role": "user", "content": "..."}] or with summary prefix.

    Example:
        >>> state = {"conversation_summary": "Cliente quiere corte de pelo."}
        >>> messages = format_llm_messages_with_summary(state, "Classify intent")
        >>> messages
        [{"role": "user", "content": "Contexto previo: Cliente quiere corte de pelo.\\n\\nClassify intent"}]
    """
    # Check if conversation summary exists
    summary = state.get("conversation_summary")

    if summary:
        # Include summary as context prefix in the user message
        combined_content = f"Contexto previo: {summary}\n\n{user_prompt}"
    else:
        # No summary, just use the prompt
        combined_content = user_prompt

    return [{"role": "user", "content": combined_content}]
