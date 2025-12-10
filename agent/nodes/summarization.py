"""
Summarization node for conversation context management.

This module implements conversation summarization to compress older messages
and maintain manageable context size for Claude API calls. Summarization is
triggered automatically after every 10 messages beyond the first 10.
"""

import logging
from pathlib import Path

from langchain_openai import ChatOpenAI

from agent.state.schemas import ConversationState
from agent.state.helpers import should_summarize, check_token_overflow

logger = logging.getLogger(__name__)

# Load summarization prompt template
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
SUMMARIZATION_PROMPT_PATH = PROMPTS_DIR / "summarization_prompt.md"


async def summarize_conversation(state: ConversationState) -> dict:
    """
    Summarize conversation to compress older messages and reduce token usage.

    This node is conditionally invoked after message addition to compress the
    conversation history. It uses Claude to generate concise summaries of messages
    beyond the recent 10-message window.

    Args:
        state: Current conversation state

    Returns:
        Updated state dict with conversation_summary field populated.
        Returns unchanged state if summarization not needed or fails.

    Summarization Strategy:
        - Triggered every 10 messages after first 10 (at 20, 30, 40, etc.)
        - Compresses messages into 2-3 sentence Spanish summary
        - Combines with existing summary for multi-batch conversations
        - Stores result in conversation_summary field
        - Graceful degradation on API failure

    Token Overflow Protection:
        - If >70% of Claude's 200k context → aggressive summarization
        - If still overflowing → escalate to human

    Example State Flow:
        Input:  {total_message_count: 20, messages: [...10 recent...]}
        Output: {conversation_summary: "Cliente quiere corte...", ...}
    """
    try:
        # Step 1: Check if summarization is needed
        if not should_summarize(state):
            return state  # Skip summarization, return unchanged

        # Step 2: Load summarization prompt template
        with open(SUMMARIZATION_PROMPT_PATH, "r", encoding="utf-8") as f:
            prompt_template = f.read()

        # Step 3: Format messages for summarization
        # Note: Recent 10 messages are in state["messages"]
        # Older messages have been removed by FIFO windowing, but we can
        # summarize what we have in the current window if no summary exists yet
        messages = state.get("messages", [])
        existing_summary = state.get("conversation_summary")

        # Format messages as "role: content" strings
        formatted_messages = "\n".join(
            f"{msg['role']}: {msg['content']}"
            for msg in messages
        )

        # Step 4: Replace placeholder in prompt template
        prompt_text = prompt_template.replace(
            "{messages_to_summarize}",
            formatted_messages
        )

        # Step 5: Call LLM via OpenRouter to generate summary
        # Note: Langfuse callbacks passed in graph config are automatically
        # inherited by this LLM invocation (LangChain callback propagation)
        from shared.config import get_settings
        settings = get_settings()

        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            temperature=0.3,  # Deterministic summaries
            max_tokens=300,   # 2-3 sentences ~100-200 tokens
            request_timeout=20.0,  # 20s timeout for summarization
            max_retries=2,  # Retry 2x on transient failures
            default_headers={
                "HTTP-Referer": settings.SITE_URL,
                "X-Title": settings.SITE_NAME,
            }
        )

        response = await llm.ainvoke([{"role": "user", "content": prompt_text}])
        new_summary_text = response.content.strip()

        # Step 6: Combine with existing summary if present
        if existing_summary:
            combined_summary = f"{existing_summary}\n\n{new_summary_text}"
        else:
            combined_summary = new_summary_text

        # Step 7: Check for token overflow
        overflow_check = check_token_overflow({
            **state,
            "conversation_summary": combined_summary
        })

        if overflow_check["overflow"]:
            action = overflow_check.get("action")
            conversation_id = state.get("conversation_id", "unknown")

            if action == "aggressive_summarize":
                # Reduce recent messages from 10 to 5
                logger.warning(
                    f"Applying aggressive summarization for conversation {conversation_id}"
                )
                # Keep only last 5 messages
                messages = messages[-5:]
            elif action == "escalate":
                # Conversation too complex, flag for human takeover
                logger.error(
                    f"Token overflow unresolved for conversation {conversation_id}, "
                    f"flagging for escalation"
                )
                return {
                    **state,
                    "conversation_summary": combined_summary,
                    "messages": messages,
                    "escalated": True,
                    "escalation_reason": "token_overflow"
                }

        # Step 8: Log summarization event
        conversation_id = state.get("conversation_id", "unknown")
        total_messages = state.get("total_message_count", 0)
        logger.info(
            f"Summarized conversation {conversation_id}, "
            f"total messages: {total_messages}, "
            f"summary length: {len(combined_summary)} chars"
        )

        # Step 9: Return updated state with summary
        return {
            **state,
            "conversation_summary": combined_summary,
            "messages": messages  # May be reduced if aggressive summarization applied
        }

    except Exception as e:
        # Graceful degradation: log error and return unchanged state
        conversation_id = state.get("conversation_id", "unknown")
        logger.error(
            f"Summarization failed for conversation {conversation_id}: {e}",
            exc_info=True
        )
        return state
