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
# Generic TTL cache helper (AD1: DRY — same pattern for base + overlay caches)
# ============================================================================


class _TtlCache:
    """Thread-safe async TTL cache for a single value.

    Provides `get_or_load(loader_fn)` to return a cached value or call the
    loader on a cache miss.  An `asyncio.Lock` prevents concurrent loads
    (thundering-herd protection).
    """

    def __init__(self, ttl_minutes: int = 10) -> None:
        self._data: Any = None
        self._expires_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._ttl = timedelta(minutes=ttl_minutes)

    def is_valid(self) -> bool:
        """Return True when the cached value exists and has not expired."""
        return self._data is not None and datetime.now() < self._expires_at  # type: ignore[operator]

    async def get_or_load(self, loader_fn) -> Any:
        """Return the cached value, or invoke *loader_fn* on a miss.

        *loader_fn* may be a regular callable or a coroutine function —
        both are handled transparently.
        """
        async with self._lock:
            if self.is_valid():
                return self._data
            if asyncio.iscoroutinefunction(loader_fn):
                self._data = await loader_fn()
            else:
                self._data = loader_fn()
            self._expires_at = datetime.now() + self._ttl
            return self._data

    def invalidate(self) -> None:
        """Immediately expire the cached value (forces re-load on next access)."""
        self._data = None
        self._expires_at = None


# ============================================================================
# Module-level caches (10-minute TTL each)
# ============================================================================

_base_prompt_cache = _TtlCache(ttl_minutes=10)
_overlay_caches: dict[str, _TtlCache] = {}  # keyed by normalised mode name


def _get_overlay_cache(mode_name: str) -> _TtlCache:
    """Return (or lazily create) the per-mode overlay TTL cache."""
    if mode_name not in _overlay_caches:
        _overlay_caches[mode_name] = _TtlCache(ttl_minutes=10)
    return _overlay_caches[mode_name]


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

    Note: shared/glossary.md is NOT included — the service catalog is served
    dynamically by the search_services and query_info tools.

    Cached for 10 minutes with async lock for thread safety.

    Returns:
        str: Concatenated system prompt (~1,400 tokens)
    """

    def _load() -> str:
        logger.info("Cache miss - loading system prompt from disk")
        identity = load_markdown("identity.md", "shared")
        critical_rules = load_markdown("critical_rules.md", "shared")
        # NOTE: glossary.md intentionally excluded — tools serve the service catalog
        prompt = "".join([identity, "\n\n---\n\n", critical_rules])
        logger.info(
            "System prompt cached (TTL: 10 min, %d chars, ~%d tokens)",
            len(prompt),
            len(prompt) // 4,
        )
        return prompt

    return await _base_prompt_cache.get_or_load(_load)


def clear_prompt_cache() -> None:
    """
    Clear both the system prompt cache and all mode overlay caches.

    Forces the next call to get_system_prompt() / load_mode_overlay() to reload
    from disk.  Useful for:
    - Prompt updates that need immediate reflection
    - Testing and debugging
    - Manual cache invalidation
    """
    _base_prompt_cache.invalidate()
    for cache in _overlay_caches.values():
        cache.invalidate()
    logger.info("System prompt cache cleared (base + all overlays)")


async def load_mode_overlay(
    mode_name: str | None,
    mode_context: dict,
    step_info: dict | None = None,
    substep: str | None = None,
) -> str:
    """Load (and cache) the mode overlay for the current prompt context.

    Each mode's overlay file is cached independently via a per-mode
    `_TtlCache` instance (10-minute TTL, asyncio.Lock for safety).
    """
    if not mode_name:
        return ""
    normalized_mode = mode_name.strip().upper()
    overlay_path = _MODE_OVERLAY_FILES.get(normalized_mode)
    if overlay_path is None:
        logger.warning("load_mode_overlay: unknown mode '%s'", mode_name)
        return ""
    subdir, file_name = overlay_path.rsplit("/", 1)

    cache = _get_overlay_cache(normalized_mode)
    return await cache.get_or_load(lambda: load_markdown(file_name, subdir))


# ============================================================================
# Message Building Helpers
# ============================================================================


def build_step_context(
    state: ConversationState,
    mode_context: dict,
    step_info: dict | None = None,
    *,
    policy_values: dict | None = None,
) -> str:
    """
    Build dynamic context for a specific booking step.

    Creates context string with:
    - Current step information
    - Collected data so far
    - Booking policy values (if provided and step is booking-related)
    - Conversation summary (if available)

    Args:
        state: Current conversation state
        mode_context: Mode-specific context data
        step_info: Optional step-specific info (step name, etc.)
        policy_values: Optional dict with DB-loaded booking policy config.
            When provided, booking policy lines are appended for BOOKING steps.
            Supported keys: ``minimum_booking_days_advance``,
            ``cancellation_window_hours``.

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
        collected_data.append(f"Cualquier profesional disponible: {scoped_ctx['soonest_any_slot']}")
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
        collected_data.append(f"Sin disponibilidad para {stylist_name} en el rango solicitado")

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
                if hint_lower in val_lower or val_lower in hint_lower or hint_lower in label_lower:
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
            collected_data.append(f"  Pista del sistema: {audience_hint or 'ninguna'}")
            collected_data.append(
                "  INSTRUCCIÓN: Presentá estas opciones al cliente de forma natural "
                "para resolver la clarificación."
            )

    # Surface candidate services for disambiguation context
    candidate_services = scoped_ctx.get("candidate_services")
    if candidate_services and not scoped_ctx.get("service_name"):
        names = [s.get("name", "") for s in candidate_services[:5] if isinstance(s, dict)]
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

    # Inject booking policy values for booking-related steps (AD2)
    if policy_values:
        _booking_steps = {
            "service_selection",
            "add_ons",
            "stylist_selection",
            "slot_selection",
            "confirmation",
            "notes",
        }
        current_step = (step_info or {}).get("step") or mode_context.get("booking_step", "")
        if current_step in _booking_steps:
            min_days = policy_values.get("minimum_booking_days_advance")
            cancel_window = policy_values.get("cancellation_window_hours")
            if min_days is not None:
                parts.append(f"Política: reservas con mínimo {min_days} días de anticipación.")
            if cancel_window is not None:
                parts.append(f"Política: cancelaciones hasta {cancel_window}h antes de la cita.")

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
    dynamic_context_override: str | None = None,
) -> tuple[list, int]:
    """
    Build a complete message list using the layered prompt approach.

    Assembly order (AD1 — dynamic context last for recency attention):
    1. SystemMessage: Cached system prompt (from shared/) — ~800 tokens
    2. SystemMessage: Optional mode overlay — ~200-900 tokens
    3. HumanMessage/AIMessage: Recent conversation history (optional)
    4. SystemMessage: Dynamic context — LAST for model recency attention (~200-600 tokens)

    Args:
        state: Current conversation state
        mode_context: Mode-specific context data
        step_info: Optional step-specific info
        include_history: Whether to include conversation history
        history_limit: Max number of history messages to include
        mode_name: Optional active mode name for overlay loading
        substep: Optional booking substep override
        dynamic_context_override: If provided, replaces the default build_step_context()
            output. Used by BookingMode to inject its richer dynamic context.

    Returns:
        tuple[list, int]: (messages, dynamic_context_index) where dynamic_context_index
            is the index of the dynamic context SystemMessage for mid-loop refresh.
    """
    from langchain_core.messages import AIMessage

    messages = []

    # 1. System prompt (cached, ~800 tokens)
    system_prompt = await get_system_prompt()
    messages.append(SystemMessage(content=system_prompt))

    # 2. Optional mode overlay (now async — uses per-mode TTL cache)
    mode_overlay = await load_mode_overlay(mode_name, mode_context, step_info, substep)
    if mode_overlay:
        messages.append(SystemMessage(content=mode_overlay))

    # 3. Recent conversation history (if enabled)
    if include_history:
        for msg in state.get("messages", [])[-history_limit:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

    # 4. Dynamic context — LAST SystemMessage (AD1: recency position for high attention)
    # CRITICAL: Must be SystemMessage so the LLM treats it as internal context.
    # Using HumanMessage causes the LLM to echo it back to the user (context leak).
    if dynamic_context_override is not None:
        dynamic_content = dynamic_context_override
    else:
        # Load policy values for booking context injection (T7 — graceful degradation)
        policy_values = None
        try:
            from agent.prompts.dynamic_context import get_policy_values

            policy_values = await get_policy_values()
        except Exception as exc:
            logger.debug("Policy values load failed (non-critical, continuing without): %s", exc)

        dynamic_content = build_step_context(
            state, mode_context, step_info, policy_values=policy_values
        )
    dynamic_msg_index = len(messages)
    messages.append(SystemMessage(content=dynamic_content))

    return messages, dynamic_msg_index


__all__ = [
    "load_markdown",
    "get_system_prompt",
    "clear_prompt_cache",
    "load_mode_overlay",
    "build_step_context",
    "build_layered_messages",
    "_STEP_VISIBLE_FIELDS",
]
