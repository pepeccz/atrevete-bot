"""Conversation graph factories.

The authoritative production/runtime graph is the v6 mode-based pipeline:

    preprocess -> router -> mode dispatcher -> mode node -> summarize -> END

Runtime-facing factories must delegate to `create_graph()` so production and
compatibility imports use the same architecture.
"""

import logging
from typing import Any, Callable
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select

from agent.nodes.summarization import summarize_conversation
from agent.prompts import load_maite_system_prompt
from agent.services.customer_memory_service import read_customer_memories
from agent.state.schemas import ConversationState
from agent.state.helpers import add_message, should_summarize
from database.connection import get_async_session
from database.models import Customer

# Configure logger
logger = logging.getLogger(__name__)

# Security: maximum allowed length for user messages
MAX_USER_MESSAGE_LENGTH = 2000

# Lazy-loaded system prompt cache
_MAITE_SYSTEM_PROMPT_CACHE: str | None = None


def get_maite_system_prompt() -> str:
    """
    Get Maite system prompt with lazy-loading and caching.

    Returns:
        str: The Maite system prompt content
    """
    global _MAITE_SYSTEM_PROMPT_CACHE

    if _MAITE_SYSTEM_PROMPT_CACHE is None:
        _MAITE_SYSTEM_PROMPT_CACHE = load_maite_system_prompt()
        logger.info(f"Maite system prompt loaded ({len(_MAITE_SYSTEM_PROMPT_CACHE)} characters)")

    return _MAITE_SYSTEM_PROMPT_CACHE


# For backward compatibility
MAITE_SYSTEM_PROMPT = get_maite_system_prompt


# REMOVED: _extract_suggested_name, _has_pending_greeting_step,
# GREETING_CONFIRM_SUGGESTED, GREETING_ASK_EXPLICIT, NAME_READABLE_PATTERN
# (dead code after customer-name-handling refactor)


async def check_customer_exists(phone: str) -> tuple[bool, Customer | None]:
    """
    Check if customer exists in database WITHOUT creating.

    v6.2: This function replaces ensure_customer_exists() to support deferred
    customer creation. Customers are now created AFTER name confirmation,
    not automatically on first message.

    Args:
        phone: Customer phone number in E.164 format (e.g., +34623226544)

    Returns:
        Tuple of (exists: bool, customer: Customer | None)

    Example:
        >>> exists, customer = await check_customer_exists("+34612345678")
        >>> if exists:
        ...     print(f"Welcome back, {customer.first_name}!")
        ... else:
        ...     print("New customer - trigger name confirmation")
    """
    async with get_async_session() as session:
        try:
            stmt = select(Customer).where(Customer.phone == phone)
            result = await session.execute(stmt)
            customer = result.scalar_one_or_none()
            return (customer is not None, customer)
        except Exception as e:
            logger.error(f"Error checking customer exists for phone {phone}: {e}", exc_info=True)
            return (False, None)


# ============================================================================
# v6.0 Mode-Based Graph — router_node + create_graph
# ============================================================================

# Auto-escalation threshold
AUTO_ESCALATION_THRESHOLD = 3

# Module-level singleton for IntentRouter
_intent_router = None


def _get_llm_client():
    """
    Create and return a new ChatOpenAI LLM client for v6.0 mode nodes.

    This function is a thin factory used by create_graph() so that tests can
    mock it via patch("agent.graphs.conversation_flow._get_llm_client").
    """
    from langchain_openai import ChatOpenAI
    from shared.config import get_settings

    settings = get_settings()
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.OPENROUTER_API_KEY,
        temperature=0.3,
        request_timeout=30.0,
        max_retries=2,
        default_headers={
            "HTTP-Referer": settings.SITE_URL,
            "X-Title": settings.SITE_NAME,
        },
    )


def _get_intent_router():
    """Get or create the module-level IntentRouter singleton.

    v7.1: keyword-only classifier — no LLM client needed. Ambiguous results
    are resolved by the mode node's main LLM turn.
    """
    global _intent_router
    if _intent_router is None:
        from agent.routing.intent_router import IntentRouter

        _intent_router = IntentRouter()
    return _intent_router


def _is_booking_related_query(user_message: str) -> bool:
    """Check if an ask_info query is related to the current booking flow.

    Questions about stylists, availability, time slots, or the selected
    service should stay in BOOKING mode, not digress to GENERAL.
    """
    if not user_message:
        return False
    msg_lower = user_message.lower()
    # Keywords that indicate the question is about the current booking
    BOOKING_RELATED_TERMS = {
        # Stylists
        "estilista",
        "peluquera",
        "peluquero",
        "profesional",
        "profesionales",
        "quién",
        "quien",
        "cuál",
        "cual",
        "cuáles",
        "cuales",
        "disponible",
        "disponibles",
        "disponibilidad",
        # Time/slots
        "horario",
        "horarios",
        "hora",
        "horas",
        "hueco",
        "huecos",
        "cuándo",
        "cuando",
        "mañana",
        "tarde",
        "semana",
        # Temporal — days of week
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "hoy",
        "mañana",
        "pasado",
        "semana que viene",
        "próxima semana",
        # Booking verbs
        "reservar",
        "agendar",
        "cancelar",
        "cambiar",
        "modificar",
        "confirmar",
        # Preferences
        "preferencia",
        "prefiero",
        "cualquiera",
        "no importa",
        "da igual",
        # Retry
        "intentar",
        "otra vez",
        "de nuevo",
        "reintentar",
        # Questions
        "cuántas",
        "cuáles",
        "tiene",
        "hay",
        # Current service context
        "cuánto tarda",
        "cuanto tarda",
        "duración",
        "duracion",
        "cuánto dura",
        "cuanto dura",
        "cuánto cuesta",
        "cuanto cuesta",
        "precio",
    }
    return any(term in msg_lower for term in BOOKING_RELATED_TERMS)


# Phrases that explicitly signal the user wants to LEAVE booking mode
_BOOKING_EXIT_PHRASES = {
    "salir",
    "otra cosa",
    "dejalo",
    "dejémoslo",
    "no quiero reservar",
    "olvidalo",
}


def _wants_to_exit_booking(message: str) -> bool:
    """Check if the user explicitly wants to leave the booking flow."""
    if not message:
        return False
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in _BOOKING_EXIT_PHRASES)


def _normalize_handoff_text(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _preserve_mode_context(context: dict | None, target_mode: str) -> dict:
    """Preserve mode context during mode transitions."""
    ctx = dict(context) if context else {}
    if target_mode == "ESCALATION":
        ctx["awaiting_human"] = True
    return ctx


def _looks_like_service_confirmation(user_message: str) -> bool:
    normalized = _normalize_handoff_text(user_message)
    if not normalized:
        return False

    if normalized == "1":
        return True

    confirmation_phrases = (
        "si",
        "dale",
        "ok",
        "vale",
        "ese",
        "esa",
        "ese mismo",
        "esa misma",
        "quiero ese",
        "quiero esa",
        "reservalo",
        "me va",
        "me sirve",
        "perfecto",
        "genial",
    )
    return normalized in confirmation_phrases


def _resolve_general_candidate_selection(
    user_message: str,
    candidate_services: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not candidate_services:
        return None

    normalized = _normalize_handoff_text(user_message)
    if not normalized:
        return None

    if normalized.isdigit():
        index = int(normalized) - 1
        if 0 <= index < len(candidate_services):
            return candidate_services[index]

    for service in candidate_services:
        service_name = str(service.get("name") or "")
        if service_name and _normalize_handoff_text(service_name) in normalized:
            return service

    if len(candidate_services) == 1 and _looks_like_service_confirmation(user_message):
        return candidate_services[0]

    return None


async def _get_catalog_stylist_names() -> list[str]:
    """Return a sorted list of active stylist names from the catalog cache.

    Uses the same 5-minute TTL cache as catalog_builder to avoid extra DB queries.
    Falls back to an empty list on any error — never raises.
    """
    try:
        from sqlalchemy import select as sa_select

        from database.connection import get_async_session
        from database.models import Stylist

        async with get_async_session() as session:
            result = await session.execute(
                sa_select(Stylist.name).where(Stylist.is_active == True).order_by(Stylist.name)
            )
            names = [row[0] for row in result.all()]
        # Longest names first so "Ana Maria" is matched before "Ana"
        names.sort(key=lambda n: len(n), reverse=True)
        return names
    except Exception as exc:
        logger.warning("_get_catalog_stylist_names: failed to load stylists: %s", exc)
        return []


async def _extract_booking_hints(user_message: str) -> dict[str, str | None]:
    """Extract preferred stylist and date hints from user message.

    Used when first entering BOOKING mode to capture upfront preferences
    ("con Pilar", "el viernes") so the LLM can skip asking for them again.

    WS-6: Stylist names are now loaded dynamically from the DB/cache instead
    of from a hardcoded KNOWN_STYLISTS list, so newly added stylists are
    captured automatically.

    Returns dict with keys: preferred_stylist_name, preferred_date_hint.
    Both may be None. Never raises — robustness guaranteed.
    """
    import re

    if not user_message:
        return {"preferred_stylist_name": None, "preferred_date_hint": None}

    try:
        msg_lower = user_message.lower()

        # Stylist detection — dynamic list from catalog (longest-first to avoid prefix clashes)
        stylist_names = await _get_catalog_stylist_names()
        preferred_stylist = None
        for name in stylist_names:
            if re.search(r"\b" + re.escape(name.lower()) + r"\b", msg_lower):
                preferred_stylist = name.title()
                break

        # Date hint — Spanish date expressions (raw phrase passed to find_next_available)
        DATE_PATTERN = re.compile(
            r"(?:el\s+)?(?:próxim[oa]\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"
            r"|ma[nñ]ana"
            r"|pasado\s+ma[nñ]ana"
            r"|(?:el\s+)?\d{1,2}(?:\s+de\s+\w+)?"
            r"|esta\s+semana"
            r"|(?:la\s+)?semana\s+que\s+viene"
            r"|próxim[oa]\s+semana",
            re.IGNORECASE,
        )
        date_match = DATE_PATTERN.search(user_message)
        preferred_date = date_match.group(0).strip() if date_match else None

        return {
            "preferred_stylist_name": preferred_stylist,
            "preferred_date_hint": preferred_date,
        }
    except Exception:
        return {"preferred_stylist_name": None, "preferred_date_hint": None}


def _should_transition_general_to_booking(
    mode_context: dict | None,
    intent: str,
) -> bool:
    """Return True when GeneralMode should hand off to BOOKING.

    Tiered certainty:
    - HIGH (resolved_service present): accept 'confirm' or 'ambiguous'
    - MEDIUM (candidate_services or pending_clarifications, no resolved): 'confirm' only
    - LOW (no handoff or empty): always False
    """
    handoff = (mode_context or {}).get("general_booking_handoff") or {}
    if not handoff:
        return False
    resolved = handoff.get("resolved_service")
    candidates = handoff.get("candidate_services") or handoff.get("pending_clarifications")
    if resolved:
        return intent in ("confirm", "ambiguous")
    if candidates:
        return intent == "confirm"
    return False


def _build_general_booking_handoff(state: ConversationState, user_message: str) -> dict[str, Any]:
    mode_context = state.get("mode_context") or {}
    handoff = mode_context.get("general_booking_handoff")
    if not isinstance(handoff, dict):
        return {}

    resolved_service = handoff.get("resolved_service")
    if isinstance(resolved_service, dict):
        # Flat dict — LLM reads catalog from prompt, no BookingContext needed
        return {k: v for k, v in resolved_service.items() if v is not None}

    # Support both plural (new) and singular (legacy) key
    pending_clarifications = handoff.get("pending_clarifications")
    if isinstance(pending_clarifications, list) and pending_clarifications:
        return {"pending_clarifications": pending_clarifications}
    pending_clarification = handoff.get("pending_clarification")
    if isinstance(pending_clarification, dict):
        return {"pending_clarifications": [pending_clarification]}

    candidate_services = handoff.get("candidate_services")
    if isinstance(candidate_services, list):
        selected_service = _resolve_general_candidate_selection(user_message, candidate_services)
        if isinstance(selected_service, dict):
            return {k: v for k, v in selected_service.items() if v is not None}

    return {}


async def _maybe_escalate(node_result: dict, state: ConversationState) -> dict:
    """
    Inline escalation hook. Called after mode.handle() in general and booking nodes.
    If escalation_triggered=True in the result, calls perform_escalation() in the same turn.
    Does NOT route to ESCALATION mode — that's handled by the router separately.

    NOTE: This is intentionally NOT called in escalation_node_fn to avoid loops.
    """
    from agent.services.escalation_service import perform_escalation

    error_count = node_result.get("error_count", state.get("error_count", 0))
    triggered = (
        node_result.get("escalation_triggered")
        or state.get("escalation_triggered")
        or error_count >= 3
    )
    already_performed = node_result.get("_escalation_performed") or state.get(
        "_escalation_performed"
    )

    if not triggered or already_performed:
        return node_result

    is_technical = (
        error_count >= 3
        or state.get("escalation_reason") == "technical_error"
        or node_result.get("escalation_reason") == "technical_error"
    )

    esc_result = None
    try:
        esc_result = await perform_escalation(
            conversation_id=str(state.get("conversation_id", "")),
            customer_phone=state.get("customer_phone") or "",
            reason=state.get("escalation_reason") or "manual_request",
            source="auto_error" if is_technical else "manual",
            is_technical_error=is_technical,
        )
    except Exception as exc:
        logger.warning(f"_maybe_escalate: perform_escalation failed: {exc}")

    node_result["_escalation_performed"] = True

    # Propagate user_message from escalation result if not already set by the mode node
    if (
        esc_result is not None
        and esc_result.user_message
        and not node_result.get("_escalation_message_set")
    ):
        node_result = {
            **node_result,
            **add_message(state, "assistant", esc_result.user_message),
            "_escalation_message_set": True,
        }

    return node_result


# ============================================================================
# Transition Table — declarative routing (replaces cascading if/elif)
# ============================================================================

# A target is either a mode name (str) or a callable resolver.
# Resolvers receive (state, intent_result) and return a mode name.
TransitionTarget = str | Callable[..., str]


def _resolve_booking_ask_info(state: ConversationState, intent_result: Any) -> str:
    """Resolve BOOKING + ask_info: stay in BOOKING if query is booking-related."""
    user_message = _get_last_user_msg_text(state)
    if _is_booking_related_query(user_message):
        return "BOOKING"
    booking_ctx = state.get("booking_context") or {}
    has_active = bool(
        booking_ctx.get("last_services")
        or booking_ctx.get("offered_slots")
        or booking_ctx.get("selected_slot")
    )
    if has_active and not _wants_to_exit_booking(user_message):
        return "BOOKING"
    return "GENERAL"


def _resolve_general_confirm(state: ConversationState, intent_result: Any) -> str:
    """Resolve GENERAL + confirm: transition to BOOKING if handoff data exists."""
    mode_context = state.get("mode_context") or {}
    if _should_transition_general_to_booking(mode_context, intent_result.intent):
        return "BOOKING"
    return "GENERAL"


def _get_last_user_msg_text(state: ConversationState) -> str:
    """Extract the last user message text from state messages."""
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


TRANSITION_TABLE: dict[tuple[str, str], TransitionTarget] = {
    # BOOKING mode transitions
    ("BOOKING", "reschedule"): "APPOINTMENT_MANAGEMENT",
    ("BOOKING", "check_appointments"): "APPOINTMENT_MANAGEMENT",
    ("BOOKING", "escalate"): "ESCALATION",
    ("BOOKING", "ask_info"): _resolve_booking_ask_info,
    ("BOOKING", "cancel"): "BOOKING",
    ("BOOKING", "reject"): "BOOKING",
    ("BOOKING", "DEFAULT"): "BOOKING",
    # ESCALATION mode transitions
    ("ESCALATION", "ask_info"): "GENERAL",
    ("ESCALATION", "greet"): "GREETING",
    ("ESCALATION", "check_appointments"): "APPOINTMENT_MANAGEMENT",
    ("ESCALATION", "book"): "BOOKING",
    ("ESCALATION", "DEFAULT"): "ESCALATION",
    # APPOINTMENT_MANAGEMENT mode transitions
    ("APPOINTMENT_MANAGEMENT", "book"): "BOOKING",
    ("APPOINTMENT_MANAGEMENT", "DEFAULT"): "APPOINTMENT_MANAGEMENT",
    # GENERAL mode transitions
    ("GENERAL", "book"): "BOOKING",
    ("GENERAL", "reschedule"): "APPOINTMENT_MANAGEMENT",
    ("GENERAL", "check_appointments"): "APPOINTMENT_MANAGEMENT",
    ("GENERAL", "cancel"): "APPOINTMENT_MANAGEMENT",
    ("GENERAL", "escalate"): "ESCALATION",
    ("GENERAL", "confirm"): _resolve_general_confirm,
    ("GENERAL", "DEFAULT"): "GENERAL",
    # GREETING mode transitions
    ("GREETING", "book"): "BOOKING",
    ("GREETING", "cancel"): "APPOINTMENT_MANAGEMENT",
    ("GREETING", "reschedule"): "APPOINTMENT_MANAGEMENT",
    ("GREETING", "check_appointments"): "APPOINTMENT_MANAGEMENT",
    ("GREETING", "escalate"): "ESCALATION",
    ("GREETING", "DEFAULT"): "GENERAL",
}


def _lookup_transition(current_mode: str, intent: str) -> TransitionTarget:
    """Look up the transition target for a (mode, intent) pair.

    Falls back to (mode, "DEFAULT"), then to "GENERAL" as ultimate fallback.
    """
    target = TRANSITION_TABLE.get((current_mode, intent))
    if target is not None:
        return target
    target = TRANSITION_TABLE.get((current_mode, "DEFAULT"))
    if target is not None:
        return target
    return "GENERAL"


# ============================================================================
# router_node — v7.0 transition-table based
# ============================================================================


async def router_node(state: ConversationState) -> dict[str, Any]:
    """
    v7.0 router_node: Classify intent and determine which mode to activate.

    Uses a declarative TRANSITION_TABLE for mode resolution with hard gates
    for escalation, confirmation replies, and first-interaction greeting.

    Routing steps:
    1. Hard gate: escalation_triggered → ESCALATION
    2. Hard gate: error_count >= 3 → ESCALATION
    3. Classify intent (keyword fast-path)
    4. Hard gate: pending_confirmation + confirm/reject/cancel → CONFIRMATION_REPLY
    5. Pre-table: first_interaction + book → GREETING (with booking hints)
    6. Table lookup → resolve callables
    7. Post-table override: explicit handoff → ESCALATION
    8. Same mode → return {mode_context: intent_data}
    9. Different mode → transition_mode() + side effects
    """
    from agent.state.schemas import transition_mode
    from agent.routing.intent_router import _is_explicit_handoff

    conversation_id = state.get("conversation_id", "unknown")
    current_mode = state.get("current_mode") or "GREETING"
    customer_name = state.get("customer_name")
    is_first_interaction = state.get("is_first_interaction", False)
    error_count = state.get("error_count", 0)
    escalation_triggered = state.get("escalation_triggered", False)

    # Find last user message
    user_message = _get_last_user_msg_text(state)

    logger.info(
        "router_node | conversation_id=%s | current_mode=%s | is_first=%s | "
        "customer_name=%s | error_count=%d",
        conversation_id,
        current_mode,
        is_first_interaction,
        customer_name,
        error_count,
    )

    # ── Hard gate 1: Already escalated ──
    if escalation_triggered:
        mode_ctx = state.get("mode_context", {})
        escalation_done = (
            current_mode == "ESCALATION"
            and mode_ctx.get("escalation_step") == "DONE"
        )
        if not escalation_done:
            return {"current_mode": "ESCALATION", "last_node": "router"}
        # Escalation complete — fall through to table lookup for normal routing

    # ── Hard gate 2: Auto-escalation threshold ──
    if error_count >= AUTO_ESCALATION_THRESHOLD:
        logger.warning("router_node: auto-escalation (error_count=%d)", error_count)
        return {"current_mode": "ESCALATION", "last_node": "router"}

    # ── Step 3: Classify intent ──
    intent_router = _get_intent_router()
    _mode_context = state.get("mode_context") or {}
    _booking_ctx = state.get("booking_context") or {}
    _booking_step = None
    if _booking_ctx.get("offered_slots") and not _booking_ctx.get("selected_slot"):
        _booking_step = "slot_selection"
    try:
        from agent.routing.intent_router import IntentResult

        intent_result = await intent_router.classify(
            text=user_message,
            current_mode=current_mode,
            booking_step=_booking_step,
        )
    except Exception as exc:
        logger.error(
            "router_node: intent classification failed | conversation_id=%s | error=%s",
            conversation_id,
            exc,
        )
        from agent.routing.intent_router import IntentResult

        intent_result = IntentResult(
            intent="ambiguous",
            confidence=0.0,
            raw_input=user_message,
            mode_hint=None,
        )

    intent_data = {
        "last_intent": intent_result.intent,
        "last_intent_confidence": intent_result.confidence,
    }

    # ── Hard gate 3: Pending appointment confirmation reply ──
    pending_confirmation_id = state.get("pending_confirmation_appointment_id")
    if pending_confirmation_id and intent_result.intent in ("confirm", "reject", "cancel"):
        return {
            "current_mode": "CONFIRMATION_REPLY",
            "mode_context": {
                "pending_confirmation_appointment_id": pending_confirmation_id,
                "last_intent": intent_result.intent,
                "last_intent_confidence": intent_result.confidence,
            },
            "last_node": "router",
        }

    # ── Pre-table: first interaction + book → BOOKING directly (skip GREETING turn) ──
    if is_first_interaction and intent_result.intent == "book":
        from agent.modes.greeting_mode import _build_booking_handoff_context

        booking_hints_first = await _extract_booking_hints(user_message) if user_message else {}
        handoff_ctx = _build_booking_handoff_context(user_message) if user_message else {}

        initial_booking_ctx: dict[str, Any] = {}
        if handoff_ctx.get("opening_booking_request"):
            initial_booking_ctx["opening_booking_request"] = handoff_ctx[
                "opening_booking_request"
            ]
        if handoff_ctx.get("service_audience_hint"):
            initial_booking_ctx["service_audience_hint"] = handoff_ctx["service_audience_hint"]
        if booking_hints_first.get("preferred_stylist_name"):
            initial_booking_ctx["preferred_stylist_name"] = booking_hints_first[
                "preferred_stylist_name"
            ]
        if booking_hints_first.get("preferred_date_hint"):
            initial_booking_ctx["preferred_date_hint"] = booking_hints_first["preferred_date_hint"]

        transition_result: dict[str, Any] = {
            **transition_mode(state, "BOOKING", context_update=intent_data),
            "last_node": "router",
        }
        if initial_booking_ctx:
            transition_result["booking_context"] = initial_booking_ctx
        return transition_result

    # ── Pre-table: first interaction + greet → GREETING ──
    # Guard: don't eject from BOOKING (the table handles BOOKING inertia)
    if (
        is_first_interaction
        and intent_result.intent == "greet"
        and current_mode not in ("BOOKING",)
    ):
        return {
            "current_mode": "GREETING",
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # ── Step 6: Table lookup ──
    target = _lookup_transition(current_mode, intent_result.intent)

    # ── Step 7: Resolve callables ──
    if callable(target):
        target = target(state, intent_result)

    # ── Post-table override: explicit handoff → ESCALATION ──
    if (
        intent_result.intent in ("ask_info", "ambiguous")
        and current_mode != "ESCALATION"
        and _is_explicit_handoff(user_message)
    ):
        logger.info(
            "router_node: explicit-handoff override → ESCALATION | message=%r",
            user_message[:80],
        )
        target = "ESCALATION"

    # ── Step 8: Same mode → no transition, just update intent data ──
    if target == current_mode:
        return {"mode_context": {**intent_data}, "last_node": "router"}

    # ── Step 9: Different mode → transition with side effects ──
    logger.info(
        "router_node: transition %s → %s | intent=%s | conversation_id=%s",
        current_mode,
        target,
        intent_result.intent,
        conversation_id,
    )

    # Side effect: LEAVING BOOKING → save draft
    if current_mode == "BOOKING" and target != "BOOKING":
        transition_update = transition_mode(state, target)
        draft_contexts = dict(transition_update.get("draft_contexts") or {})
        draft_contexts["BOOKING"] = _preserve_mode_context(
            state.get("mode_context") or {},
            target,
        )
        return {
            **transition_update,
            "draft_contexts": draft_contexts,
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # Side effect: ENTERING BOOKING (from another mode)
    if target == "BOOKING":
        draft_contexts = state.get("draft_contexts") or {}
        restored_booking_draft = draft_contexts.get("BOOKING") or {}
        general_booking_handoff = {}

        # Build handoff from GENERAL if applicable
        if current_mode == "GENERAL":
            if _should_transition_general_to_booking(_mode_context, intent_result.intent):
                general_booking_handoff = _build_general_booking_handoff(state, user_message)
            elif not restored_booking_draft:
                general_booking_handoff = _build_general_booking_handoff(state, user_message)

        booking_hints = await _extract_booking_hints(user_message) if user_message else {}
        booking_context_for_mode = {
            **general_booking_handoff,
            **booking_hints,
            **restored_booking_draft,
            **intent_data,
        }

        # Populate booking_context state field with durable handoff hints
        initial_booking_ctx: dict[str, Any] = {}
        if booking_hints.get("preferred_stylist_name"):
            initial_booking_ctx["preferred_stylist_name"] = booking_hints[
                "preferred_stylist_name"
            ]
        if booking_hints.get("preferred_date_hint"):
            initial_booking_ctx["preferred_date_hint"] = booking_hints["preferred_date_hint"]
        if restored_booking_draft:
            initial_booking_ctx = {**restored_booking_draft, **initial_booking_ctx}

        transition_result: dict[str, Any] = {
            **transition_mode(state, "BOOKING", context_update=booking_context_for_mode),
            "last_node": "router",
        }
        if initial_booking_ctx:
            transition_result["booking_context"] = initial_booking_ctx
        return transition_result

    # Generic transition (no special side effects)
    return {
        **transition_mode(state, target),
        "mode_context": {**intent_data},
        "last_node": "router",
    }


async def preprocess_node_v6(state: ConversationState) -> dict[str, Any]:
    """v6.0 preprocess: adds message, detects first interaction, checks customer."""
    conversation_id = state.get("conversation_id", "unknown")
    user_message = state.get("user_message")

    if not user_message:
        return {"last_node": "preprocess", "pending_confirmation_appointment_id": None}

    # Security: hard truncate user input to prevent context inflation and injection
    if len(user_message) > MAX_USER_MESSAGE_LENGTH:
        logger.warning(
            "preprocess_node_v6: message truncated | conversation_id=%s | original_len=%d",
            conversation_id,
            len(user_message),
        )
        user_message = user_message[:MAX_USER_MESSAGE_LENGTH]

    existing_messages = state.get("messages", [])
    is_first_interaction = len(existing_messages) == 0

    msg_update = add_message(state, "user", user_message)
    updates: dict[str, Any] = {
        **msg_update,
        "is_first_interaction": is_first_interaction,
        "last_node": "preprocess",
        "user_message": None,  # FIX BUG-NEW-1: clear transient user_message after persisting to messages
    }

    customer_phone = state.get("customer_phone")
    if customer_phone:
        try:
            customer_exists, customer = await check_customer_exists(customer_phone)
            if customer_exists and customer:
                updates["customer_id"] = str(customer.id)
                updates["customer_name"] = customer.first_name
                logger.info(
                    "preprocess_node_v6: returning customer | customer_id=%s | name=%s",
                    customer.id,
                    customer.first_name,
                )
                # Load cross-conversation memories (Store API / PG fallback)
                try:
                    memories = await read_customer_memories(customer_phone)
                    updates["customer_memories"] = memories
                    if memories:
                        logger.info(
                            "preprocess_node_v6: loaded customer memories | phone=%s | visit_count=%s",
                            customer_phone,
                            memories.get("visit_count"),
                        )
                except Exception as mem_exc:
                    logger.warning(
                        "preprocess_node_v6: customer memory read failed | phone=%s | error=%s",
                        customer_phone,
                        mem_exc,
                    )
                    updates["customer_memories"] = None
            else:
                raw_display_name = state.get("pending_whatsapp_name") or state.get("customer_name")
                updates["customer_name"] = None
                updates["customer_id"] = None
                updates["pending_whatsapp_name"] = raw_display_name
                updates["customer_memories"] = None
        except Exception as e:
            logger.error(
                "preprocess_node_v6: customer check failed | conversation_id=%s | error=%s",
                conversation_id,
                e,
            )

    resolved_customer_id = updates.get("customer_id") or state.get("customer_id")
    if not resolved_customer_id:
        updates["pending_confirmation_appointment_id"] = None
        return updates

    try:
        from agent.services.confirmation_service import get_pending_confirmations

        pending_appts = await get_pending_confirmations(UUID(str(resolved_customer_id)))
        updates["pending_confirmation_appointment_id"] = (
            str(pending_appts[0].id) if pending_appts else None
        )
    except Exception as exc:
        logger.warning(
            "preprocess_node_v6: pending confirmation check failed | conversation_id=%s | error=%s",
            conversation_id,
            exc,
        )
        updates["pending_confirmation_appointment_id"] = None

    return updates


def create_graph(checkpointer: Any = None, store: Any = None) -> "CompiledStateGraph":
    """
    Create the authoritative v6 mode-based StateGraph.

    Flow: preprocess → router → [greeting|general|booking|escalation] → summarize → END

    Args:
        checkpointer: LangGraph checkpoint saver (AsyncRedisSaver in production, None in tests)
        store: LangGraph Store (AsyncRedisStore in production, None/InMemoryStore in tests).
               When provided, enables cross-conversation customer memory via get_store().

    Returns:
        Compiled StateGraph
    """
    from agent.modes.greeting_mode import build_greeting_node
    from agent.modes.general_mode import build_general_node
    from agent.modes.booking_mode import BookingMode
    from agent.modes.escalation_mode import build_escalation_node
    from agent.modes.appointment_management_mode import AppointmentManagementMode
    from agent.modes.confirmation_reply_node import confirmation_reply_node
    from agent.routing.intent_router import IntentResult

    def _get_llm():
        return _get_llm_client()

    # M3/M4: GREETING, GENERAL and ESCALATION run as create_agent factories (or
    # pure FSMs for escalation). Factories are instantiated once per graph
    # build; the LLM is resolved lazily per turn so tests can patch
    # ``_get_llm_client``.
    _greeting_node_impl = build_greeting_node(llm_factory=_get_llm)
    _general_node_impl = build_general_node(llm_factory=_get_llm)
    _escalation_node_impl = build_escalation_node()

    def mode_dispatcher(state: ConversationState) -> str:
        """Conditional edge: current_mode → node name."""
        mode_to_node = {
            "GREETING": "greeting",
            "GENERAL": "general",
            "BOOKING": "booking",
            "ESCALATION": "escalation",
            "CONFIRMATION_REPLY": "confirmation_reply",
            "APPOINTMENT_MANAGEMENT": "appointment_management",
        }
        return mode_to_node.get(state.get("current_mode") or "GENERAL", "general")

    async def greeting_node_fn(state: ConversationState) -> dict[str, Any]:
        # M3: create_agent + TokenTrackingMiddleware (no BaseModeNode).
        # The mode_context-derived IntentResult that legacy code built here is
        # no longer needed — the greeting factory reads last_intent directly
        # from state["mode_context"] inside _resolve_target_mode().
        result = await _greeting_node_impl(state)
        return {**result, "last_node": "greeting"}

    async def general_node_fn(state: ConversationState) -> dict[str, Any]:
        # M4: create_agent + TokenTrackingMiddleware, no tools.
        result = await _general_node_impl(state)
        result = await _maybe_escalate(result, state)
        return {**result, "last_node": "general"}

    async def booking_node_fn(state: ConversationState) -> dict[str, Any]:
        mode_context = state.get("mode_context") or {}
        intent = IntentResult(
            intent=mode_context.get("last_intent", "book"),
            confidence=mode_context.get("last_intent_confidence", 0.9),
            raw_input="",
            mode_hint="BOOKING",
        )
        mode = BookingMode(tools=[], llm_client=_get_llm())
        result = await mode.handle(state=state, intent=intent)
        result = await _maybe_escalate(result, state)
        return {**result, "last_node": "booking"}

    async def escalation_node_fn(state: ConversationState) -> dict[str, Any]:
        # M4: pure FSM factory — no LLM, no tools, no middleware.
        result = await _escalation_node_impl(state)
        return {**result, "last_node": "escalation"}

    async def appointment_management_node_fn(state: ConversationState) -> dict[str, Any]:
        mode_context = state.get("mode_context") or {}
        intent = IntentResult(
            intent=mode_context.get("last_intent", "manage_appointment"),
            confidence=mode_context.get("last_intent_confidence", 0.9),
            raw_input="",
            mode_hint="APPOINTMENT_MANAGEMENT",
        )
        mode = AppointmentManagementMode(tools=[], llm_client=_get_llm())
        result = await mode.handle(state=state, intent=intent)
        return {**result, "last_node": "appointment_management"}

    # Build graph
    graph = StateGraph(ConversationState)

    graph.add_node("preprocess", preprocess_node_v6)
    graph.add_node("router", router_node)
    graph.add_node("greeting", greeting_node_fn)
    graph.add_node("general", general_node_fn)
    graph.add_node("booking", booking_node_fn)
    graph.add_node("escalation", escalation_node_fn)
    graph.add_node("appointment_management", appointment_management_node_fn)
    graph.add_node("confirmation_reply", confirmation_reply_node)
    graph.add_node("summarize", summarize_conversation)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "router")
    graph.add_conditional_edges(
        "router",
        mode_dispatcher,
        {
            "greeting": "greeting",
            "general": "general",
            "booking": "booking",
            "escalation": "escalation",
            "confirmation_reply": "confirmation_reply",
            "appointment_management": "appointment_management",
        },
    )
    graph.add_edge("greeting", "summarize")
    graph.add_edge("general", "summarize")
    graph.add_edge("booking", "summarize")
    graph.add_edge("escalation", "summarize")
    graph.add_edge("appointment_management", "summarize")
    graph.add_edge("confirmation_reply", "summarize")
    graph.add_edge("summarize", END)

    compiled = graph.compile(checkpointer=checkpointer, store=store)
    logger.info("authoritative v6 mode-based graph compiled successfully")
    return compiled


def create_conversation_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[ConversationState, Any, Any, Any]:
    """Backward-compatible wrapper around the authoritative v6 graph factory."""
    logger.info("create_conversation_graph() delegating to create_graph()")
    return create_graph(checkpointer=checkpointer)
