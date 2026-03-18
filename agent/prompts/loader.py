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
from shared.config import get_settings

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

_BOOKING_PROMPT_LEGACY_STEP_ALIASES = {
    "customer_data": "notes",
    "datetime_selection": "slot_selection",
}

_BOOKING_SUBSTEP_FILE_MAP: dict[str, str] = {
    "service_selection": "service_selection.md",
    "add_ons": "add_ons.md",
    "stylist_selection": "stylist_selection.md",
    "slot_selection": "slot_selection.md",
    "customer_name": "customer_name.md",
    "notes": "notes.md",
    "confirmation": "confirmation.md",
    "completed": "completed.md",
}

_MODE_OVERLAY_FILES: dict[str, str] = {
    "GREETING": "modes/greeting.md",
    "BOOKING": "modes/booking.md",
    "GENERAL": "modes/general.md",
    "ESCALATION": "modes/escalation.md",
}


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


def _use_substep_prompts() -> bool:
    """Return whether booking substep overlays are enabled."""

    try:
        return get_settings().USE_SUBSTEP_PROMPTS
    except Exception:
        return True


def _resolve_booking_substep(
    mode_context: dict,
    step_info: dict | None = None,
    substep: str | None = None,
) -> str | None:
    """Resolve the canonical booking substep from explicit or legacy inputs."""

    from agent.modes.booking_context import normalize_booking_substep

    raw_substep = substep or mode_context.get("booking_step")
    if raw_substep is None and step_info is not None:
        raw_substep = step_info.get("step_name")
    if raw_substep is None:
        return None

    aliased = _BOOKING_PROMPT_LEGACY_STEP_ALIASES.get(str(raw_substep).lower(), raw_substep)

    try:
        return normalize_booking_substep(str(aliased).lower()).value
    except ValueError:
        return None


def load_mode_overlay(
    mode_name: str | None,
    mode_context: dict,
    step_info: dict | None = None,
    substep: str | None = None,
) -> str:
    """Load the appropriate mode overlay for the current prompt context."""

    if not mode_name:
        return ""

    normalized_mode = mode_name.strip().upper()

    if normalized_mode != "BOOKING":
        overlay_path = _MODE_OVERLAY_FILES.get(normalized_mode)
        if overlay_path is None:
            logger.warning("load_mode_overlay: unknown mode '%s'", mode_name)
            return ""

        subdir, file_name = overlay_path.rsplit("/", 1)
        return load_markdown(file_name, subdir)

    if not _use_substep_prompts():
        overlay_path = _MODE_OVERLAY_FILES["BOOKING"]
        subdir, file_name = overlay_path.rsplit("/", 1)
        return load_markdown(file_name, subdir)

    resolved_substep = _resolve_booking_substep(mode_context, step_info, substep)
    if resolved_substep is None:
        return ""

    file_name = _BOOKING_SUBSTEP_FILE_MAP.get(resolved_substep)
    if not file_name:
        return ""

    return load_markdown(file_name, "modes/booking")


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

    # Customer name is intentionally NOT injected into prompt context.
    # The LLM cannot leak what it doesn't know. Name is stored in DB only.
    customer_phone = state.get("customer_phone")
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
    if mode_context.get("selected_services"):
        collected_data.append(
            "Servicios seleccionados: " + ", ".join(mode_context["selected_services"])
        )
    if mode_context.get("recurrent_stylist_name"):
        recurrent_line = f"Estilista habitual: {mode_context['recurrent_stylist_name']}"
        if mode_context.get("recurrent_stylist_slot_summary"):
            recurrent_line += f" ({mode_context['recurrent_stylist_slot_summary']})"
        collected_data.append(recurrent_line)
    if mode_context.get("prefetch_error"):
        collected_data.append(
            "⚠️ PREFETCH FALLIDO: Los datos de estilistas no se pudieron cargar. "
            "USA la herramienta list_stylists para obtenerlos."
        )
    prefetched_stylists = mode_context.get("prefetched_stylists")
    if prefetched_stylists:
        collected_data.append("Estilistas disponibles:")
        for stylist in prefetched_stylists:
            collected_data.append(
                f"  - {stylist['name']}: {stylist.get('next_slot_summary', 'Sin disponibilidad')}"
            )
    if mode_context.get("soonest_any_slot"):
        collected_data.append(
            f"Cualquier profesional disponible: {mode_context['soonest_any_slot']}"
        )
    if mode_context.get("slot_summary"):
        collected_data.append(f"Horario: {mode_context['slot_summary']}")
    if mode_context.get("first_name"):
        collected_data.append(f"Nombre para la reserva: {mode_context['first_name']}")
    if mode_context.get("notes"):
        collected_data.append(f"Notas: {mode_context['notes']}")
    if mode_context.get("pending_recommendations"):
        collected_data.append(
            "Servicios sugeridos: " + ", ".join(mode_context["pending_recommendations"])
        )
    if mode_context.get("availability_start_date"):
        collected_data.append(
            f"Fecha pedida por la clienta: {mode_context['availability_start_date']}"
        )
    if mode_context.get("availability_time_range"):
        collected_data.append(
            f"Franja pedida por la clienta: {mode_context['availability_time_range']}"
        )
    if mode_context.get("substitution_made"):
        substitution_reason = mode_context.get("substitution_reason")
        date_requested = mode_context.get("date_requested")
        date_substituted = mode_context.get("date_substituted")
        min_valid_date = mode_context.get("min_valid_date")

        if substitution_reason == "minimum_days_rule" and date_requested and min_valid_date:
            collected_data.append(
                "Fecha solicitada ajustada: "
                f"{date_requested} no cumple la anticipacion minima. "
                f"Primera fecha valida: {min_valid_date}"
            )
        elif date_requested and date_substituted:
            collected_data.append(
                f"Fecha solicitada ajustada: {date_requested} -> {date_substituted}"
            )
    if mode_context.get("no_slots_for_stylist"):
        stylist_name = mode_context.get("stylist_name") or "la estilista elegida"
        collected_data.append(
            f"Sin disponibilidad para {stylist_name} en el rango solicitado"
        )

    if collected_data:
        parts.append("\nDatos recopilados:")
        for item in collected_data:
            parts.append(f"- {item}")

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
    mode_name: str | None = None,
    substep: str | None = None,
) -> list:
    """
    Build a complete message list using the layered prompt approach.

    Returns messages in the format:
    1. SystemMessage: Cached system prompt (from shared/)
    2. SystemMessage: Optional mode overlay
    3. HumanMessage: Dynamic step context
    4. Recent conversation history (optional)

    Args:
        state: Current conversation state
        mode_context: Mode-specific context data
        step_info: Optional step-specific info
        include_history: Whether to include conversation history
        history_limit: Max number of history messages to include
        mode_name: Optional active mode name for overlay loading
        substep: Optional booking substep override

    Returns:
        list: List of LangChain message objects
    """
    from langchain_core.messages import AIMessage

    messages = []

    # 1. System prompt (cached, ~2,200 tokens)
    system_prompt = await get_system_prompt()
    messages.append(SystemMessage(content=system_prompt))

    # 2. Optional mode overlay
    mode_overlay = load_mode_overlay(mode_name, mode_context, step_info, substep)
    if mode_overlay:
        messages.append(SystemMessage(content=mode_overlay))

    # 3. Dynamic context (~300 tokens)
    # CRITICAL: Must be SystemMessage so the LLM treats it as internal context.
    # Using HumanMessage causes the LLM to echo it back to the user (context leak).
    dynamic_context = build_step_context(state, mode_context, step_info)
    messages.append(SystemMessage(content=dynamic_context))

    # 4. Recent conversation history (if enabled)
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
    "load_mode_overlay",
    "build_step_context",
    "build_layered_messages",
]
