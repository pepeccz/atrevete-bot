"""Conversation graph factories.

The authoritative production/runtime graph is the v6 mode-based pipeline:

    preprocess -> router -> mode dispatcher -> mode node -> summarize -> END

Runtime-facing factories must delegate to `create_graph()` so production and
compatibility imports use the same architecture.
"""

import logging
from typing import Any
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select

from agent.nodes.summarization import summarize_conversation
from agent.prompts import load_maite_system_prompt
from agent.state.schemas import ConversationState
from agent.state.helpers import add_message, should_summarize
from database.connection import get_async_session
from database.models import Customer

# Configure logger
logger = logging.getLogger(__name__)

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
    )


def _get_intent_router():
    """Get or create the module-level IntentRouter singleton."""
    global _intent_router
    if _intent_router is None:
        from langchain_openai import ChatOpenAI
        from agent.routing.intent_router import IntentRouter
        from shared.config import get_settings

        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
            temperature=0.3,
        )
        _intent_router = IntentRouter(llm_client=llm)
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


def _service_to_booking_context(service: dict[str, Any]) -> dict[str, Any]:
    booking_context = {
        "service_id": service.get("id"),
        "service_name": service.get("name", ""),
        "service_category": service.get("category", ""),
        "service_duration_minutes": service.get("duration_minutes"),
        "service_family": service.get("family"),
    }

    recommendations = [
        str(item) for item in service.get("combo_recommendations", []) if str(item).strip()
    ]
    if recommendations:
        booking_context["pending_recommendations"] = recommendations
        booking_context["recommendations_shown"] = False

    return booking_context


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


def _build_general_booking_handoff(state: ConversationState, user_message: str) -> dict[str, Any]:
    mode_context = state.get("mode_context") or {}
    handoff = mode_context.get("general_booking_handoff")
    if not isinstance(handoff, dict):
        return {}

    resolved_service = handoff.get("resolved_service")
    if isinstance(resolved_service, dict):
        return _service_to_booking_context(resolved_service)

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
            return _service_to_booking_context(selected_service)

    return {}


async def router_node(state: ConversationState) -> dict[str, Any]:
    """
    v6.0 router_node: Classify intent and determine which mode to activate.

    Routing rules (priority order):
    1. escalation_triggered=True → ESCALATION
    2. error_count >= 3 → ESCALATION (auto-escalation)
    2.5 pending confirmation reply + intent in {confirm, reject, cancel} → CONFIRMATION_REPLY
    3. pending GREETING subflow → GREETING with classified intent
    4. customer_name is None + intent in {greet, ambiguous} → GREETING
    5. intent=escalate → ESCALATION
    6. current_mode=BOOKING and intent ask_info → GENERAL with preserved draft
    7. current_mode=BOOKING and intent not cancel/reject/ask_info → stay BOOKING
    7.5 current_mode=ESCALATION and intent not book → stay ESCALATION (inertia)
    8. intent=book → BOOKING
    9. intent=greet (not in BOOKING) → GREETING
    10. Default → GENERAL
    """
    from agent.modes.booking_context import preserve_booking_context
    from agent.state.schemas import transition_mode

    conversation_id = state.get("conversation_id", "unknown")
    current_mode = state.get("current_mode") or "GREETING"
    customer_name = state.get("customer_name")
    is_first_interaction = state.get("is_first_interaction", False)
    error_count = state.get("error_count", 0)
    escalation_triggered = state.get("escalation_triggered", False)

    # Find last user message
    messages = state.get("messages", [])
    turn_count = len(messages)
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    logger.info(
        "router_node | conversation_id=%s | current_mode=%s | is_first=%s | "
        "customer_name=%s | error_count=%d",
        conversation_id,
        current_mode,
        is_first_interaction,
        customer_name,
        error_count,
    )

    # Rule 1: Already escalated
    if escalation_triggered:
        return {"current_mode": "ESCALATION", "last_node": "router"}

    # Rule 2: Auto-escalation threshold
    if error_count >= AUTO_ESCALATION_THRESHOLD:
        logger.warning("router_node: auto-escalation (error_count=%d)", error_count)
        return {"current_mode": "ESCALATION", "last_node": "router"}

    # Classify intent (keyword + LLM hybrid) before confirmation/greeting rules
    # so both subflows can use the same classified result.
    # Pass booking_step from mode_context so bare digit replies in slot_selection
    # are classified as "confirm" instead of falling to the LLM as "reject".
    intent_router = _get_intent_router()
    _mode_context = state.get("mode_context") or {}
    # Derive booking_step for intent classifier bare-digit shortcut
    _booking_step = None
    if _mode_context.get("offered_slots") and not _mode_context.get("selected_slot"):
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

    # Rule 2.5: Customer replying to a pending appointment confirmation template
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

    # Rule 3: REMOVED — greeting subflow no longer has pending steps
    # (name confirmation was removed in customer-name-handling refactor)

    # Rule 4: Unknown customers only go through GREETING on their FIRST
    # interaction. The is_first_interaction guard prevents re-entry loops
    # when customer_name is None on subsequent turns.
    # Booking inertia (T-2.3): also skip if booking_step is active — prevents
    # bouncing back to GREETING mid-booking when customer_name is None.
    _has_active_booking = bool(
        _mode_context.get("service_id")
        or _mode_context.get("offered_slots")
        or _mode_context.get("selected_slot")
    )
    if (
        not customer_name
        and is_first_interaction
        and current_mode != "BOOKING"
        and not _has_active_booking
        and intent_result.intent in ("greet", "ambiguous")
    ):
        greeting_context = {
            **(state.get("mode_context") or {}),
            **intent_data,
            "is_first_interaction": is_first_interaction,
            "turn_count": turn_count,
        }
        return {
            "current_mode": "GREETING",
            "mode_context": greeting_context,
            "last_node": "router",
        }

    # Rule 5: Escalation intent
    if intent_result.intent == "escalate":
        transition_update = transition_mode(state, "ESCALATION")
        if current_mode == "BOOKING":
            draft_contexts = dict(transition_update.get("draft_contexts") or {})
            draft_contexts["BOOKING"] = preserve_booking_context(
                state.get("mode_context") or {},
                "ESCALATION",
            )
            transition_update["draft_contexts"] = draft_contexts
        return {
            **transition_update,
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # Rule 6: BOOKING digressions → GENERAL (only for truly unrelated queries)
    if current_mode == "BOOKING" and intent_result.intent == "ask_info":
        if _is_booking_related_query(user_message):
            # Stay in BOOKING — the question is about the current booking flow
            logger.info(
                "router_node: ask_info in BOOKING kept in BOOKING (booking-related query) | message=%r",
                user_message[:80],
            )
            return {"mode_context": {**intent_data}, "last_node": "router"}
        # Booking inertia: if booking data is being collected and the user hasn't
        # explicitly asked to leave, keep them in BOOKING to avoid accidental
        # digressions (T-2.3).
        if _has_active_booking and not _wants_to_exit_booking(user_message):
            logger.info(
                "router_node: ask_info in active BOOKING kept via inertia | message=%r",
                user_message[:80],
            )
            return {"mode_context": {**intent_data}, "last_node": "router"}
        # Truly unrelated → digress to GENERAL with preserved draft context
        transition_update = transition_mode(state, "GENERAL")
        draft_contexts = dict(transition_update.get("draft_contexts") or {})
        draft_contexts["BOOKING"] = preserve_booking_context(
            state.get("mode_context") or {},
            "GENERAL",
        )
        return {
            **transition_update,
            "draft_contexts": draft_contexts,
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # Rule 7: Stay in BOOKING unless cancel/reject or GENERAL digression
    if current_mode == "BOOKING" and intent_result.intent not in ("cancel", "reject", "ask_info"):
        return {"mode_context": {**intent_data}, "last_node": "router"}

    # Rule 7.5: Stay in ESCALATION unless the user starts a new topic (book)
    # Mirrors Rule 7 (BOOKING inertia). The escalation FSM collects issue
    # summary and contact preference; responses like "Por WhatsApp" are
    # classified as confirm/ambiguous by the router but must NOT eject the
    # user from the intake flow.
    if current_mode == "ESCALATION" and intent_result.intent not in ("book",):
        return {"mode_context": {**intent_data}, "last_node": "router"}

    # Rule 8: Book intent → BOOKING
    if intent_result.intent == "book":
        # BUG-1C FIX: if already in BOOKING, skip transition_mode (which sends __reset__)
        # to avoid wiping mode_context mid-flow. Use the same no-reset return shape as Rule 6.
        if current_mode == "BOOKING":
            return {"mode_context": {**intent_data}, "last_node": "router"}

        draft_contexts = state.get("draft_contexts") or {}
        restored_booking_draft = draft_contexts.get("BOOKING") or {}
        general_booking_handoff = {}
        if current_mode == "GENERAL" and not restored_booking_draft:
            general_booking_handoff = _build_general_booking_handoff(state, user_message)

        booking_context = {**general_booking_handoff, **restored_booking_draft, **intent_data}
        return {
            **transition_mode(state, "BOOKING", context_update=booking_context),
            "last_node": "router",
        }

    # Rule 9: Greet intent → GREETING (only if name unknown AND first interaction)
    # BUG-NEW-3 FIX: is_first_interaction guard prevents anonymous returning users
    # from getting stuck in GREETING→GENERAL loop on subsequent turns.
    if (
        intent_result.intent == "greet"
        and current_mode not in ("BOOKING",)
        and not customer_name
        and is_first_interaction  # Only re-enter GREETING on genuine first turns
    ):
        return {
            "current_mode": "GREETING",
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # Rule 9.5: Explicit-handoff override (T2.2)
    # If the intent fell through to ask_info/ambiguous but the user explicitly
    # asked for a human, force ESCALATION before the GENERAL fallback.
    # This catches phrases that score 0.70 in _keyword_matches() and miss the
    # 0.80 fast-path threshold.
    from agent.routing.intent_router import _is_explicit_handoff

    if (
        intent_result.intent in ("ask_info", "ambiguous")
        and current_mode != "ESCALATION"
        and _is_explicit_handoff(user_message)
    ):
        logger.info(
            "router_node: explicit-handoff override → ESCALATION | message=%r",
            user_message[:80],
        )
        transition_update = transition_mode(state, "ESCALATION")
        if current_mode == "BOOKING":
            from agent.modes.booking_context import preserve_booking_context

            draft_contexts = dict(transition_update.get("draft_contexts") or {})
            draft_contexts["BOOKING"] = preserve_booking_context(
                state.get("mode_context") or {},
                "ESCALATION",
            )
            transition_update["draft_contexts"] = draft_contexts
        return {
            **transition_update,
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # Rule 10: Default → GENERAL
    target_mode = "GENERAL"
    if current_mode == "BOOKING" and intent_result.intent in ("cancel", "reject"):
        target_mode = "BOOKING"

    if target_mode != current_mode:
        return {
            **transition_mode(state, target_mode),
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    return {"mode_context": {**intent_data}, "last_node": "router"}


async def preprocess_node_v6(state: ConversationState) -> dict[str, Any]:
    """v6.0 preprocess: adds message, detects first interaction, checks customer."""
    conversation_id = state.get("conversation_id", "unknown")
    user_message = state.get("user_message")

    if not user_message:
        return {"last_node": "preprocess", "pending_confirmation_appointment_id": None}

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
            else:
                raw_display_name = state.get("pending_whatsapp_name") or state.get("customer_name")
                updates["customer_name"] = None
                updates["customer_id"] = None
                updates["pending_whatsapp_name"] = raw_display_name
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


def create_graph(checkpointer: Any = None) -> "CompiledStateGraph":
    """
    Create the authoritative v6 mode-based StateGraph.

    Flow: preprocess → router → [greeting|general|booking|escalation] → summarize → END

    Args:
        checkpointer: LangGraph checkpoint saver (AsyncRedisSaver in production, None in tests)

    Returns:
        Compiled StateGraph
    """
    from agent.modes.greeting_mode import GreetingMode
    from agent.modes.general_mode import GeneralMode
    from agent.modes.booking_mode import BookingMode
    from agent.modes.escalation_mode import EscalationMode
    from agent.modes.confirmation_reply_node import confirmation_reply_node
    from agent.routing.intent_router import IntentResult

    def _get_llm():
        return _get_llm_client()

    def mode_dispatcher(state: ConversationState) -> str:
        """Conditional edge: current_mode → node name."""
        mode_to_node = {
            "GREETING": "greeting",
            "GENERAL": "general",
            "BOOKING": "booking",
            "ESCALATION": "escalation",
            "CONFIRMATION_REPLY": "confirmation_reply",
        }
        return mode_to_node.get(state.get("current_mode") or "GENERAL", "general")

    async def greeting_node_fn(state: ConversationState) -> dict[str, Any]:
        mode_context = state.get("mode_context") or {}
        intent = IntentResult(
            intent=mode_context.get("last_intent", "greet"),
            confidence=mode_context.get("last_intent_confidence", 0.9),
            raw_input="",
            mode_hint="GREETING",
        )
        mode = GreetingMode(tools=[], llm_client=_get_llm())
        result = await mode.handle(state=state, intent=intent)
        return {**result, "last_node": "greeting"}

    async def general_node_fn(state: ConversationState) -> dict[str, Any]:
        mode_context = state.get("mode_context") or {}
        intent = IntentResult(
            intent=mode_context.get("last_intent", "ask_info"),
            confidence=mode_context.get("last_intent_confidence", 0.8),
            raw_input="",
            mode_hint="GENERAL",
        )
        mode = GeneralMode(tools=[], llm_client=_get_llm())
        result = await mode.handle(state=state, intent=intent)
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
        return {**result, "last_node": "booking"}

    async def escalation_node_fn(state: ConversationState) -> dict[str, Any]:
        mode_context = state.get("mode_context") or {}
        intent = IntentResult(
            intent=mode_context.get("last_intent", "escalate"),
            confidence=mode_context.get("last_intent_confidence", 1.0),
            raw_input="",
            mode_hint="ESCALATION",
        )
        mode = EscalationMode(tools=[], llm_client=_get_llm())
        result = await mode.handle(state=state, intent=intent)
        return {**result, "last_node": "escalation"}

    # Build graph
    graph = StateGraph(ConversationState)

    graph.add_node("preprocess", preprocess_node_v6)
    graph.add_node("router", router_node)
    graph.add_node("greeting", greeting_node_fn)
    graph.add_node("general", general_node_fn)
    graph.add_node("booking", booking_node_fn)
    graph.add_node("escalation", escalation_node_fn)
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
        },
    )
    graph.add_edge("greeting", "summarize")
    graph.add_edge("general", "summarize")
    graph.add_edge("booking", "summarize")
    graph.add_edge("escalation", "summarize")
    graph.add_edge("confirmation_reply", "summarize")
    graph.add_edge("summarize", END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("authoritative v6 mode-based graph compiled successfully")
    return compiled


def create_conversation_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph[ConversationState, Any, Any, Any]:
    """Backward-compatible wrapper around the authoritative v6 graph factory."""
    logger.info("create_conversation_graph() delegating to create_graph()")
    return create_graph(checkpointer=checkpointer)
