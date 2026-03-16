"""Conversation graph factories.

The authoritative production/runtime graph is the v6 mode-based pipeline:

    preprocess -> router -> mode dispatcher -> mode node -> summarize -> END

Runtime-facing factories must delegate to `create_graph()` so production and
compatibility imports use the same architecture.
"""

import logging
import re
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

# Regex pattern for "readable" names (only letters, spaces, accents)
NAME_READABLE_PATTERN = re.compile(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]+$')

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

GREETING_CONFIRM_SUGGESTED = "confirm_suggested_name"
GREETING_ASK_EXPLICIT = "ask_name"


def _extract_suggested_name(display_name: str | None) -> str | None:
    """Return a readable first name from a raw WhatsApp/Chatwoot display name."""
    if not display_name:
        return None

    candidate = display_name.strip().split()[0] if display_name.strip() else ""
    if not candidate or candidate == "Cliente":
        return None

    if not NAME_READABLE_PATTERN.match(candidate):
        return None

    # Reject tokens with 3 or fewer chars to avoid low-confidence guesses like
    # "Sii". This also rejects real short names such as "Ana", but in that
    # case GREETING falls back to the explicit name-ask flow instead.
    if len(candidate) <= 3:
        return None

    return candidate.title()


def _has_pending_greeting_step(state: ConversationState) -> bool:
    """Return True when GREETING still owns the current turn."""
    mode_context = state.get("mode_context") or {}
    return bool(
        state.get("current_mode") == "GREETING"
        and mode_context.get("greeting_step") in {GREETING_CONFIRM_SUGGESTED, GREETING_ASK_EXPLICIT}
    )


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
            logger.error(
                f"Error checking customer exists for phone {phone}: {e}",
                exc_info=True
            )
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


async def router_node(state: ConversationState) -> dict[str, Any]:
    """
    v6.0 router_node: Classify intent and determine which mode to activate.

    Routing rules (priority order):
    1. escalation_triggered=True → ESCALATION
    2. error_count >= 3 → ESCALATION (auto-escalation)
    3. pending GREETING subflow → GREETING with classified intent
    4. classify intent before first-turn fallback
    5. is_first_interaction=True OR customer_name is None + intent=book → BOOKING
    6. is_first_interaction=True OR customer_name is None + intent!=book → GREETING
    7. intent=escalate → ESCALATION
    8. current_mode=BOOKING and intent not cancel/reject → stay BOOKING
    9. intent=book → BOOKING
    10. intent=greet (not in BOOKING) → GREETING
    11. Default → GENERAL
    """
    from agent.modes.booking_context import preserve_booking_context
    from agent.state.schemas import transition_mode

    conversation_id = state.get("conversation_id", "unknown")
    current_mode = state.get("current_mode") or "GREETING"
    customer_name = state.get("customer_name")
    is_first_interaction = state.get("is_first_interaction", False)
    error_count = state.get("error_count", 0)
    escalation_triggered = state.get("escalation_triggered", False)
    greeting_pending = _has_pending_greeting_step(state)

    # Find last user message
    messages = state.get("messages", [])
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    logger.info(
        "router_node | conversation_id=%s | current_mode=%s | is_first=%s | "
        "customer_name=%s | error_count=%d",
        conversation_id, current_mode, is_first_interaction,
        customer_name, error_count,
    )

    # Rule 1: Already escalated
    if escalation_triggered:
        return {"current_mode": "ESCALATION", "last_node": "router"}

    # Rule 2: Auto-escalation threshold
    if error_count >= AUTO_ESCALATION_THRESHOLD:
        logger.warning("router_node: auto-escalation (error_count=%d)", error_count)
        return {"current_mode": "ESCALATION", "last_node": "router"}

    # Rule 3: Existing GREETING subflow keeps ownership until resolved
    if greeting_pending and not is_first_interaction:
        intent_router = _get_intent_router()
        try:
            from agent.routing.intent_router import IntentResult
            intent = await intent_router.classify(
                text=user_message,
                current_mode="GREETING",
            )
        except Exception as exc:
            logger.error("router_node: greeting intent classification failed | error=%s", exc)
            from agent.routing.intent_router import IntentResult
            intent = IntentResult(
                intent="ambiguous",
                confidence=0.0,
                raw_input=user_message,
                mode_hint="GREETING",
            )

        return {
            "current_mode": "GREETING",
            "mode_context": {
                **(state.get("mode_context") or {}),
                "last_intent": intent.intent,
                "last_intent_confidence": intent.confidence,
            },
            "last_node": "router",
        }

    # Classify intent (keyword + LLM hybrid) before first-turn fallback so
    # booking messages can bypass GREETING on the very first turn.
    intent_router = _get_intent_router()
    try:
        from agent.routing.intent_router import IntentResult
        intent = await intent_router.classify(
            text=user_message,
            current_mode=current_mode,
        )
    except Exception as exc:
        logger.error(
            "router_node: intent classification failed | conversation_id=%s | error=%s",
            conversation_id,
            exc,
        )
        from agent.routing.intent_router import IntentResult
        intent = IntentResult(
            intent="ambiguous",
            confidence=0.0,
            raw_input=user_message,
            mode_hint=None,
        )

    intent_data = {
        "last_intent": intent.intent,
        "last_intent_confidence": intent.confidence,
    }

    # Rule 4a/4b: First interaction or name unknown.
    # BUG-1B FIX: guard against intercepting mid-booking turns where customer_name is still None.
    if is_first_interaction or (not customer_name and current_mode != "BOOKING"):
        if intent.intent == "book":
            first_turn_booking_context = {
                **intent_data,
                "is_first_interaction": is_first_interaction,
            }
            return {
                **transition_mode(state, "BOOKING", context_update=first_turn_booking_context),
                "last_node": "router",
            }

        return {
            "current_mode": "GREETING",
            "mode_context": {
                **(state.get("mode_context") or {}),
                **intent_data,
            },
            "last_node": "router",
        }

    # Rule 5: Escalation intent
    if intent.intent == "escalate":
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

    # Rule 6: BOOKING digressions → GENERAL with preserved draft context
    if current_mode == "BOOKING" and intent.intent == "ask_info":
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
    if current_mode == "BOOKING" and intent.intent not in ("cancel", "reject", "ask_info"):
        return {"mode_context": {**intent_data}, "last_node": "router"}

    # Rule 8: Book intent → BOOKING
    if intent.intent == "book":
        # BUG-1C FIX: if already in BOOKING, skip transition_mode (which sends __reset__)
        # to avoid wiping mode_context mid-flow. Use the same no-reset return shape as Rule 6.
        if current_mode == "BOOKING":
            return {"mode_context": {**intent_data}, "last_node": "router"}

        draft_contexts = state.get("draft_contexts") or {}
        restored_booking_draft = draft_contexts.get("BOOKING") or {}
        booking_context = {**restored_booking_draft, **intent_data}
        return {
            **transition_mode(state, "BOOKING", context_update=booking_context),
            "last_node": "router",
        }

    # Rule 9: Greet intent → GREETING (only if name unknown)
    if intent.intent == "greet" and current_mode not in ("BOOKING",):
        return {
            "current_mode": "GREETING",
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # Rule 10: Default → GENERAL
    target_mode = "GENERAL"
    if current_mode == "BOOKING" and intent.intent in ("cancel", "reject"):
        target_mode = "BOOKING"

    if target_mode != current_mode:
        return {
            **transition_mode(state, target_mode),
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    return {"mode_context": {**intent_data}, "last_node": "router"}


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
    from agent.routing.intent_router import IntentResult

    def _get_llm():
        return _get_llm_client()

    async def preprocess_node_v6(state: ConversationState) -> dict[str, Any]:
        """v6.0 preprocess: adds message, detects first interaction, checks customer."""
        conversation_id = state.get("conversation_id", "unknown")
        user_message = state.get("user_message")

        if not user_message:
            return {"last_node": "preprocess"}

        existing_messages = state.get("messages", [])
        is_first_interaction = len(existing_messages) == 0

        msg_update = add_message(state, "user", user_message)
        # NOTE: user_message is NOT cleared here (FIX-001)
        # It is cleared in summarize_node at the end of the pipeline

        updates: dict[str, Any] = {
            **msg_update,
            "is_first_interaction": is_first_interaction,
            "last_node": "preprocess",
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
                        customer.id, customer.first_name,
                    )
                else:
                    raw_display_name = state.get("pending_whatsapp_name") or state.get("customer_name")
                    suggested_name = _extract_suggested_name(raw_display_name)
                    greeting_step = (
                        GREETING_CONFIRM_SUGGESTED if suggested_name is not None else GREETING_ASK_EXPLICIT
                    )

                    updates["customer_name"] = None
                    updates["customer_id"] = None
                    updates["pending_whatsapp_name"] = raw_display_name

                    if not _has_pending_greeting_step(state):
                        updates["mode_context"] = {
                            "greeting_step": greeting_step,
                            "suggested_name": suggested_name,
                            "whatsapp_display_name": raw_display_name,
                        }
            except Exception as e:
                logger.error("preprocess_node_v6: customer check failed | error=%s", e)

        return updates

    def mode_dispatcher(state: ConversationState) -> str:
        """Conditional edge: current_mode → node name."""
        mode_to_node = {
            "GREETING": "greeting",
            "GENERAL": "general",
            "BOOKING": "booking",
            "ESCALATION": "escalation",
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
    graph.add_node("summarize", summarize_conversation)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "router")
    graph.add_conditional_edges("router", mode_dispatcher, {
        "greeting": "greeting",
        "general": "general",
        "booking": "booking",
        "escalation": "escalation",
    })
    graph.add_edge("greeting", "summarize")
    graph.add_edge("general", "summarize")
    graph.add_edge("booking", "summarize")
    graph.add_edge("escalation", "summarize")
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
