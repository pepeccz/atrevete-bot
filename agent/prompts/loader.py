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


_MODE_OVERLAY_FILES: dict[str, str] = {
    "GREETING": "modes/greeting.md",
    "BOOKING": "modes/booking.md",
    "GENERAL": "modes/general.md",
    "ESCALATION": "modes/escalation.md",
    "APPOINTMENT_MANAGEMENT": "modes/appointment_management.md",
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

    Note: shared/glossary.md is NOT included — the service catalog is injected
    dynamically via catalog_builder.py into the mode-specific prompt context.

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


def _genericize_service_name(
    service_name: str,
    all_service_names: list[str] | None,
) -> str:
    """Return a generic display name if the service has ambiguous siblings.

    Checks if other services share the same base name. Uses the first word
    as the base, but if the service name has a distinguishing second word
    (e.g., "Corte de Flequillo" vs "Corte Señora"), checks whether the
    two-word prefix is shared by others before genericizing.

    This prevents the LLM from seeing the exact variant and assuming it
    without asking the user.
    """
    if not all_service_names or not service_name:
        return service_name

    parts = service_name.split()
    first_word = parts[0].lower()

    # Find all services sharing the same first word (excluding self)
    same_first = [
        n for n in all_service_names
        if n.split()[0].lower() == first_word and n != service_name
    ]
    if not same_first:
        return service_name  # Unique first word — no ambiguity

    # Check if THIS service's full name is distinguishable via a unique
    # multi-word prefix. E.g., "Corte de Flequillo" — "Corte de" only appears
    # in this one service, so it's not ambiguous even though "Corte" is shared.
    if len(parts) >= 3:
        # Three-word services with a preposition (e.g., "Corte de Flequillo")
        # are usually unique sub-categories, not audience variants.
        prefix_2 = f"{parts[0]} {parts[1]}".lower()
        same_prefix_2 = [
            n for n in same_first
            if len(n.split()) >= 2 and f"{n.split()[0]} {n.split()[1]}".lower() == prefix_2
        ]
        if not same_prefix_2:
            return service_name

    # For multi-word family names (e.g., "Cultura de Color"), genericize
    # using the full base (without the differentiator like "Extra")
    if len(parts) >= 2:
        # Find the shortest common prefix shared by all siblings + self
        all_family = [service_name] + same_first
        common_words = parts[:]
        for sibling in all_family:
            sib_parts = sibling.split()
            new_common = []
            for i, w in enumerate(common_words):
                if i < len(sib_parts) and sib_parts[i].lower() == w.lower():
                    new_common.append(w)
                else:
                    break
            common_words = new_common
        if len(common_words) >= 2:
            return " ".join(common_words)

    return f"un {first_word}"


def _build_customer_memory_context(
    memories: dict[str, Any],
    all_service_names: list[str] | None = None,
) -> str:
    """Format customer memories as a Spanish-language section for prompt injection.

    Pure sync function — no I/O. Only called when memories is a non-empty dict.

    When all_service_names is provided, services with ambiguous family names
    (e.g., "Corte Señora" when "Corte Caballero" also exists) are shown
    generically (e.g., "un corte de pelo") to prevent the LLM from assuming
    the specific variant without asking the user.

    Args:
        memories: Customer preferences dict from Store/PG.
        all_service_names: Active service names from catalog (for ambiguity check).

    Returns:
        Formatted markdown section string.
    """
    lines: list[str] = []

    visit_count = memories.get("visit_count", 0)
    lines.append(f"- Visitas anteriores: {visit_count}")

    no_pref = memories.get("no_preference_stylist", False)
    preferred_stylist = memories.get("preferred_stylist_name")
    if no_pref:
        lines.append("- Sin preferencia de estilista en visitas anteriores")
    elif visit_count >= 2 and preferred_stylist:
        lines.append(
            f"- Estilista en visitas anteriores: {preferred_stylist} "
            "(pregunta si quiere la misma estilista, NO asumas)"
        )

    typical_services = memories.get("typical_services") or []
    last_visit_date = memories.get("last_visit_date")

    if typical_services:
        date_suffix = f" ({last_visit_date})" if last_visit_date else ""
        display_name = _genericize_service_name(typical_services[0], all_service_names)
        lines.append(f"- Servicio en visita anterior: {display_name}{date_suffix}")
        if len(typical_services) > 1:
            other_names = [
                _genericize_service_name(s, all_service_names)
                for s in typical_services[1:]
            ]
            lines.append(f"- Otros servicios que ha pedido: {', '.join(other_names)}")

    day = memories.get("typical_day_of_week")
    time_of_day = memories.get("typical_time_of_day")
    if day:
        time_label = {"morning": "mañana", "afternoon": "tarde"}.get(time_of_day or "", "")
        day_str = f"{day} por la {time_label}" if time_label else day
        lines.append(
            f"- Suele venir: {day_str} — pero pregunta qué día prefiere esta vez"
        )

    notes = memories.get("notes")
    if notes:
        lines.append(
            f"- Nota de visitas anteriores: {notes} "
            "(menciónalo al preguntar por notas nuevas)"
        )

    return "## Historial del cliente\n" + "\n".join(lines)


def _build_simple_dynamic_context(state: dict, mode_context: dict | None = None) -> str:
    """Build minimal dynamic context: datetime, customer phone, summary, customer memories.

    Customer names are intentionally NOT included here — the LLM reads them
    from conversation history and tool results.
    """
    import pytz

    parts = []

    # Current datetime
    now = datetime.now(pytz.timezone("Europe/Madrid"))
    parts.append(f"Fecha y hora actual: {now.strftime('%A %d de %B de %Y, %H:%M')} (Madrid)")

    # Customer phone
    phone = state.get("customer_phone") or state.get("sender_phone", "")
    if phone:
        parts.append(f"Teléfono del cliente: {phone}")

    # Conversation summary
    summary = state.get("conversation_summary", "")
    if summary:
        parts.append(f"Resumen de la conversación:\n{summary}")

    # Cross-conversation customer memories (injected when present)
    customer_memories = state.get("customer_memories")
    if customer_memories and isinstance(customer_memories, dict):
        parts.append(_build_customer_memory_context(customer_memories))

    return "\n\n".join(parts)


async def build_layered_messages(
    state: ConversationState,
    mode_context: dict,
    include_history: bool = True,
    history_limit: int = 6,
    mode_name: str | None = None,
    dynamic_context_override: str | None = None,
    include_catalog: bool = True,
) -> tuple[list, int]:
    """
    Build a complete message list using the layered prompt approach.

    Assembly order:
    1. SystemMessage: Cached system prompt (identity + critical_rules) — ~800 tokens
    2. SystemMessage: Catalog (services, stylists, business hours, policies) — from DB
    3. SystemMessage: Optional mode overlay — ~200-900 tokens
    4. HumanMessage/AIMessage: Recent conversation history (optional)
    5. SystemMessage: Dynamic context — LAST for model recency attention

    Args:
        state: Current conversation state
        mode_context: Mode-specific context data
        include_history: Whether to include conversation history
        history_limit: Max number of history messages to include
        mode_name: Optional active mode name for overlay loading
        dynamic_context_override: If provided, replaces the default _build_simple_dynamic_context()
            output. Used by BookingMode to inject its richer dynamic context.
        include_catalog: Whether to include the service catalog. Set to False for modes
            that don't need it (e.g. GREETING) to reduce context and prevent hallucinations.

    Returns:
        tuple[list, int]: (messages, dynamic_context_index) where dynamic_context_index
            is the index of the dynamic context SystemMessage for mid-loop refresh.
    """
    from langchain_core.messages import AIMessage

    from agent.prompts.catalog_builder import build_catalog_markdown

    messages = []

    # 1. System prompt (cached, ~800 tokens)
    system_prompt = await get_system_prompt()
    messages.append(SystemMessage(content=system_prompt))

    # 2. Catalog (services, stylists, business hours — DB-driven, 5-min cache)
    if include_catalog:
        catalog = await build_catalog_markdown()
        messages.append(SystemMessage(content=catalog))

    # 3. Optional mode overlay (per-mode TTL cache)
    mode_overlay = await load_mode_overlay(mode_name, mode_context)
    if mode_overlay:
        messages.append(SystemMessage(content=mode_overlay))

    # 4. Recent conversation history (if enabled)
    if include_history:
        for msg in state.get("messages", [])[-history_limit:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

    # 5. Dynamic context — LAST SystemMessage (recency position for high attention)
    # CRITICAL: Must be SystemMessage so the LLM treats it as internal context.
    # Using HumanMessage causes the LLM to echo it back to the user (context leak).
    if dynamic_context_override is not None:
        dynamic_content = dynamic_context_override
    else:
        dynamic_content = _build_simple_dynamic_context(state, mode_context)

    dynamic_msg_index = len(messages)
    messages.append(SystemMessage(content=dynamic_content))

    return messages, dynamic_msg_index


__all__ = [
    "load_markdown",
    "get_system_prompt",
    "clear_prompt_cache",
    "load_mode_overlay",
    "build_layered_messages",
    "_build_customer_memory_context",
    "_build_simple_dynamic_context",
    "_TtlCache",
]
