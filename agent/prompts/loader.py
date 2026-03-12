"""
Prompt loading utilities for the v6.0 mode-based architecture.

This module provides centralized prompt loading with caching support
for the optimized prompt system.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

# ============================================================================
# Module-level cache for system prompts (10 minute TTL)
# ============================================================================

_prompt_cache: dict[str, Any] = {
    "data": None,
    "expires_at": None,
    "lock": asyncio.Lock(),
}

CACHE_KEY = "system_prompt_v1"
CACHE_TTL_MINUTES = 10


# ============================================================================
# Prompt Loader Functions
# ============================================================================


def load_markdown(file_name: str, subdir: str = "shared") -> str:
    """
    Load a markdown file from the prompts directory.

    Args:
        file_name: Name of the markdown file (e.g., "identity.md")
        subdir: Subdirectory under prompts/ (e.g., "shared", "modes")

    Returns:
        str: Content of the markdown file, or empty string if not found
    """
    prompt_dir = Path(__file__).parent
    file_path = prompt_dir / subdir / file_name

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        logger.debug(f"Loaded {subdir}/{file_name} ({len(content)} chars)")
        return content
    except FileNotFoundError:
        logger.error(f"Prompt file not found: {file_path}")
        return ""
    except Exception as e:
        logger.error(f"Error loading {subdir}/{file_name}: {e}")
        return ""


async def get_system_prompt() -> str:
    """
    Get the cached system prompt (shared content).

    Loads and concatenates:
    - shared/identity.md
    - shared/critical_rules.md
    - shared/glossary.md

    Cached for 10 minutes with async lock for thread safety.

    Returns:
        str: Concatenated system prompt (~2,200 tokens)
    """
    now = datetime.now()

    async with _prompt_cache["lock"]:
        if (
            _prompt_cache["data"] is not None
            and _prompt_cache["expires_at"] is not None
            and _prompt_cache["expires_at"] > now
        ):
            logger.debug("Using cached system prompt (cache hit)")
            return _prompt_cache["data"]

        # Cache miss - load from disk
        logger.info("Cache miss - loading system prompt from disk")

        identity = load_markdown("identity.md", "shared")
        critical_rules = load_markdown("critical_rules.md", "shared")
        glossary = load_markdown("glossary.md", "shared")

        # Concatenate with separators
        parts = [
            identity,
            "\n\n---\n\n",
            critical_rules,
            "\n\n---\n\n",
            glossary,
        ]

        system_prompt = "".join(parts)

        # Update cache with 10-minute TTL
        _prompt_cache["data"] = system_prompt
        _prompt_cache["expires_at"] = now + timedelta(minutes=CACHE_TTL_MINUTES)

        logger.info(
            f"System prompt cached (TTL: {CACHE_TTL_MINUTES} min, "
            f"{len(system_prompt)} chars, ~{len(system_prompt) // 4} tokens)"
        )
        return system_prompt


def clear_prompt_cache() -> None:
    """
    Clear the system prompt cache.

    Forces the next call to get_system_prompt() to reload from disk.
    Useful for:
    - Prompt updates that need immediate reflection
    - Testing and debugging
    - Manual cache invalidation
    """
    _prompt_cache["data"] = None
    _prompt_cache["expires_at"] = None
    logger.info("System prompt cache cleared")


# ============================================================================
# Message Building Helpers
# ============================================================================


def build_step_context(
    state: ConversationState,
    mode_context: dict,
    step_info: dict | None = None,
) -> str:
    """
    Build dynamic context for a specific booking step.

    Creates context string with:
    - Current step information
    - Collected data so far
    - User message
    - Conversation summary (if available)

    Args:
        state: Current conversation state
        mode_context: Mode-specific context data
        step_info: Optional step-specific info (step name, etc.)

    Returns:
        str: Dynamic context string (~300 tokens)
    """
    parts: list[str] = []

    # Add temporal context
    from datetime import datetime
    import pytz

    timezone = pytz.timezone("Europe/Madrid")
    now = datetime.now(timezone)
    parts.append(f"Fecha y hora actual: {now.strftime('%A %d de %B de %Y, %H:%M')}")

    # Add customer info if available
    customer_name = state.get("customer_name")
    customer_phone = state.get("customer_phone")
    if customer_name:
        parts.append(f"Nombre del cliente: {customer_name}")
    if customer_phone:
        parts.append(f"Teléfono: {customer_phone}")

    # Add step info
    if step_info:
        step_name = step_info.get("step_name", "unknown")
        parts.append(f"Paso actual: {step_name}")

    # Add collected data from mode_context
    collected_data = []
    if mode_context.get("service_name"):
        collected_data.append(f"Servicio: {mode_context['service_name']}")
    if mode_context.get("stylist_name"):
        collected_data.append(f"Estilista: {mode_context['stylist_name']}")
    if mode_context.get("slot_summary"):
        collected_data.append(f"Horario: {mode_context['slot_summary']}")
    if mode_context.get("first_name"):
        collected_data.append(f"Nombre para la reserva: {mode_context['first_name']}")
    if mode_context.get("notes"):
        collected_data.append(f"Notas: {mode_context['notes']}")

    if collected_data:
        parts.append("\nDatos recopilados:")
        for item in collected_data:
            parts.append(f"- {item}")

    # Add user message
    user_message = state.get("user_message", "")
    if user_message:
        parts.append(f"\nMensaje del cliente: {user_message}")

    # Add conversation summary if available
    summary = state.get("conversation_summary")
    if summary:
        parts.append(f"\nContexto previo:\n{summary}")

    return "\n".join(parts)


async def build_layered_messages(
    state: ConversationState,
    mode_context: dict,
    step_info: dict | None = None,
    include_history: bool = True,
    history_limit: int = 6,
) -> list:
    """
    Build a complete message list using the layered prompt approach.

    Returns messages in the format:
    1. SystemMessage: Cached system prompt (from shared/)
    2. HumanMessage: Dynamic step context
    3. Recent conversation history (optional)

    Args:
        state: Current conversation state
        mode_context: Mode-specific context data
        step_info: Optional step-specific info
        include_history: Whether to include conversation history
        history_limit: Max number of history messages to include

    Returns:
        list: List of LangChain message objects
    """
    from langchain_core.messages import AIMessage

    messages = []

    # 1. System prompt (cached, ~2,200 tokens)
    system_prompt = await get_system_prompt()
    messages.append(SystemMessage(content=system_prompt))

    # 2. Dynamic context (~300 tokens)
    dynamic_context = build_step_context(state, mode_context, step_info)
    messages.append(HumanMessage(content=dynamic_context))

    # 3. Recent conversation history (if enabled)
    if include_history:
        for msg in state.get("messages", [])[-history_limit:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

    return messages


__all__ = [
    "load_markdown",
    "get_system_prompt",
    "clear_prompt_cache",
    "build_step_context",
    "build_layered_messages",
]
