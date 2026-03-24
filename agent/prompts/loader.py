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

_STEP_VISIBLE_FIELDS: dict[str, set[str]] = {
    "service_selection": {
        "customer_phone",
        "service_name",
        "service_category",
        "pending_clarification",
        "pending_clarifications",
        "candidate_services",
        "candidate_service_ids",
        "pending_recommendations",
        "recommendations_shown",
        "service_audience_hint",
        "implicit_service_hint",
        "selected_services",
        "service_duration_minutes",
        "conversation_summary",
    },
    "add_ons": {
        "customer_phone",
        "service_name",
        "service_category",
        "service_duration_minutes",
        "selected_services",
        "add_ons_options",
        "add_ons_declined",
        "pending_recommendations",
        "recommendations_shown",
        "conversation_summary",
    },
    "stylist_selection": {
        "customer_phone",
        "service_name",
        "service_category",
        "service_duration_minutes",
        "selected_services",
        "prefetched_stylists",
        "soonest_any_slot",
        "soonest_any_slot_candidate",
        "recurrent_stylist_name",
        "recurrent_stylist_slot_summary",
        "prefetch_error_type",
        "conversation_summary",
    },
    "slot_selection": {
        "customer_phone",
        "service_name",
        "service_duration_minutes",
        "stylist_name",
        "stylist_id",
        "selected_services",
        "offered_slots",
        "selected_slot",
        "slot_summary",
        "availability_start_date",
        "availability_time_range",
        "substitution_made",
        "substitution_reason",
        "date_requested",
        "date_substituted",
        "min_valid_date",
        "no_slots_for_stylist",
        "prefetch_error_type",
        "conversation_summary",
    },
    "customer_name": {
        "customer_phone",
        "service_name",
        "stylist_name",
        "conversation_summary",
    },
    "notes": {
        "customer_phone",
        "service_name",
        "stylist_name",
        "slot_summary",
        "selected_services",
        "conversation_summary",
    },
    "confirmation": {
        "customer_phone",
        "service_name",
        "stylist_name",
        "slot_summary",
        "notes",
        "selected_services",
        "service_duration_minutes",
        "conversation_summary",
    },
    "completed": {
        "customer_phone",
        "service_name",
        "stylist_name",
        "slot_summary",
        "notes",
        "selected_services",
        "conversation_summary",
    },
}

_MODE_OVERLAY_FILES: dict[str, str] = {
    "GREETING": "modes/greeting.md",
    "BOOKING": "modes/booking_v7.md",
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
    overlay_path = _MODE_OVERLAY_FILES.get(normalized_mode)
    if overlay_path is None:
        logger.warning("load_mode_overlay: unknown mode '%s'", mode_name)
        return ""
    subdir, file_name = overlay_path.rsplit("/", 1)
    return load_markdown(file_name, subdir)


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

    # Per-step data scoping — filter mode_context to prevent data leakage
    booking_step = mode_context.get("booking_step", "")
    visible_fields = _STEP_VISIBLE_FIELDS.get(booking_step)
    if visible_fields is not None:
        scoped_ctx = {k: v for k, v in mode_context.items() if k in visible_fields}
    else:
        scoped_ctx = mode_context  # fallback: show all

    # Add collected data from scoped context
    collected_data = []
    if scoped_ctx.get("service_name"):
        collected_data.append(f"Servicio: {scoped_ctx['service_name']}")
    if scoped_ctx.get("stylist_name"):
        collected_data.append(f"Estilista: {scoped_ctx['stylist_name']}")
    if scoped_ctx.get("selected_services"):
        collected_data.append(
            "Servicios seleccionados: " + ", ".join(scoped_ctx["selected_services"])
        )
    if scoped_ctx.get("recurrent_stylist_name"):
        recurrent_line = f"Estilista habitual: {scoped_ctx['recurrent_stylist_name']}"
        if scoped_ctx.get("recurrent_stylist_slot_summary"):
            recurrent_line += f" ({scoped_ctx['recurrent_stylist_slot_summary']})"
        collected_data.append(recurrent_line)
    prefetch_error_type = scoped_ctx.get("prefetch_error_type")
    if prefetch_error_type == "tool_error":
        collected_data.append(
            "⚠️ PREFETCH FALLIDO (error técnico): usá list_stylists como herramienta de respaldo."
        )
    elif prefetch_error_type == "no_availability":
        collected_data.append(
            "⚠️ SIN DISPONIBILIDAD: no hay estilistas disponibles. "
            "Informá al cliente y sugiere otro día."
        )
    prefetched_stylists = scoped_ctx.get("prefetched_stylists")
    if prefetched_stylists:
        collected_data.append("Estilistas disponibles:")
        for stylist in prefetched_stylists:
            collected_data.append(
                f"  - {stylist['name']}: {stylist.get('next_slot_summary', 'Sin disponibilidad')}"
            )
    if scoped_ctx.get("soonest_any_slot"):
        collected_data.append(
            f"Cualquier profesional disponible: {scoped_ctx['soonest_any_slot']}"
        )
    if scoped_ctx.get("slot_summary"):
        collected_data.append(f"Horario: {scoped_ctx['slot_summary']}")
    if scoped_ctx.get("notes"):
        collected_data.append(f"Notas: {scoped_ctx['notes']}")
    if scoped_ctx.get("pending_recommendations"):
        collected_data.append(
            "Servicios sugeridos: " + ", ".join(scoped_ctx["pending_recommendations"])
        )
    if scoped_ctx.get("availability_start_date"):
        collected_data.append(
            f"Fecha pedida por la clienta: {scoped_ctx['availability_start_date']}"
        )
    if scoped_ctx.get("availability_time_range"):
        collected_data.append(
            f"Franja pedida por la clienta: {scoped_ctx['availability_time_range']}"
        )
    if scoped_ctx.get("substitution_made"):
        substitution_reason = scoped_ctx.get("substitution_reason")
        date_requested = scoped_ctx.get("date_requested")
        date_substituted = scoped_ctx.get("date_substituted")
        min_valid_date = scoped_ctx.get("min_valid_date")

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
    if scoped_ctx.get("no_slots_for_stylist"):
        stylist_name = scoped_ctx.get("stylist_name") or "la estilista elegida"
        collected_data.append(
            f"Sin disponibilidad para {stylist_name} en el rango solicitado"
        )

    # Surface pending clarification so LLM can present options to user
    # Supports both new list (pending_clarifications) and legacy scalar
    _pc_list = scoped_ctx.get("pending_clarifications") or []
    _pc_legacy = scoped_ctx.get("pending_clarification")
    pending_clarification = _pc_list[0] if _pc_list else _pc_legacy
    if pending_clarification:
        axis = pending_clarification.get("axis", "")
        hint = pending_clarification.get("question_hint", "")
        options = pending_clarification.get("options", [])
        audience_hint = scoped_ctx.get("service_audience_hint")

        # Check if any option matches the audience hint — skip re-asking if so
        matched_option = None
        if audience_hint and axis == "audience":
            hint_lower = audience_hint.lower()
            for opt in options:
                val_lower = opt.get("value", "").lower()
                label_lower = opt.get("label", "").lower()
                if (
                    hint_lower in val_lower
                    or val_lower in hint_lower
                    or hint_lower in label_lower
                ):
                    matched_option = opt
                    break

        if matched_option:
            # Hint already matches — tell LLM to use it directly
            label = matched_option.get("label", matched_option.get("value", ""))
            service_name = matched_option.get("service_name", "")
            collected_data.append(
                f"CLARIFICACIÓN RESUELTA: La clienta ya indicó '{audience_hint}'. "
                f"Usa directamente la opción '{label}'"
                + (f" ({service_name})" if service_name else "")
                + ". No vuelvas a preguntar."
            )
        else:
            # No match — show all options for LLM to ask
            collected_data.append(f"CLARIFICACIÓN PENDIENTE ({axis}):")
            collected_data.append(f"  Pregunta: {hint}")
            collected_data.append("  Opciones:")
            for i, opt in enumerate(options, 1):
                label = opt.get("label", opt.get("value", ""))
                description = opt.get("description", "")
                if description:
                    collected_data.append(f"  {i}. {label} — {description}")
                else:
                    collected_data.append(f"  {i}. {label}")
            collected_data.append(
                f"  Pista del sistema: {audience_hint or 'ninguna'}"
            )
            collected_data.append(
                "  INSTRUCCIÓN: Presentá estas opciones al cliente de forma natural "
                "para resolver la clarificación."
            )

    # Surface candidate services for disambiguation context
    candidate_services = scoped_ctx.get("candidate_services")
    if candidate_services and not scoped_ctx.get("service_name"):
        names = [
            s.get("name", "") for s in candidate_services[:5] if isinstance(s, dict)
        ]
        if names:
            collected_data.append("Servicios candidatos: " + ", ".join(names))

    # Intent carry-over: include implicit_service_hint if present (once-only pattern)
    implicit_service_hint = scoped_ctx.get("implicit_service_hint")
    if implicit_service_hint:
        collected_data.append(f"Petición original de la clienta: {implicit_service_hint}")

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
    "_STEP_VISIBLE_FIELDS",
]
