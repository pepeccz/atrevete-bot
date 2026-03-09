"""
LangGraph StateGraph for conversation flow orchestration - v6.0 Mode-Based Architecture.

This module defines the mode-based StateGraph that replaces the old linear flow:

OLD (v3.0):
    process_incoming_message → conversational_agent → END

NEW (v6.0):
    START → preprocess_node → router_node → mode_dispatcher
        → [greeting_node | general_node | booking_node | escalation_node]
        → summarize_node → END

Mode-based routing separates concern clearly:
- GREETING: First contact, name extraction (GreetingMode)
- GENERAL: FAQs, service info, informational queries (GeneralMode)
- BOOKING: Full appointment booking flow (BookingMode)
- ESCALATION: Human handoff (EscalationMode)

The graph uses Annotated reducers in ConversationState to ensure correct
state merging across turns (no dual-write, no race conditions).
"""

import logging
import re
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select

from agent.modes.booking_mode import BookingMode
from agent.modes.escalation_mode import EscalationMode
from agent.modes.general_mode import GeneralMode
from agent.modes.greeting_mode import GreetingMode
from agent.nodes.summarization import summarize_conversation
from agent.routing.intent_router import IntentResult, IntentRouter
from agent.state.helpers import add_message, should_summarize
from agent.state.schemas import ConversationState, create_initial_state, transition_mode
from database.connection import get_async_session
from database.models import Customer
from shared.config import get_settings

logger = logging.getLogger(__name__)

# Regex pattern for "readable" names (only letters, spaces, accents)
NAME_READABLE_PATTERN = re.compile(r"^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]+$")

# Auto-escalation threshold: after this many consecutive errors, escalate to human
AUTO_ESCALATION_THRESHOLD = 3

# Module-level singleton for IntentRouter (stateless, safe to share)
_intent_router: IntentRouter | None = None


def _get_llm_client() -> ChatOpenAI:
    """
    Create an LLM client using settings from shared/config.py.

    Returns:
        ChatOpenAI configured for OpenRouter API.
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.OPENROUTER_API_KEY,
        temperature=0.3,
        request_timeout=30.0,
        max_retries=2,
    )


def _get_intent_router() -> IntentRouter:
    """
    Get or create the module-level IntentRouter singleton.

    IntentRouter is stateless, so it's safe to share across requests.
    The LLM client is created fresh each call (lightweight, no I/O).
    """
    global _intent_router
    if _intent_router is None:
        _intent_router = IntentRouter(llm_client=_get_llm_client())
    return _intent_router


async def check_customer_exists(phone: str) -> tuple[bool, Customer | None]:
    """
    Check if customer exists in database WITHOUT creating.

    v6.0: Customers are created AFTER name confirmation, not automatically
    on first message. This prevents phantom records for wrong-number contacts.

    Args:
        phone: Customer phone number in E.164 format (e.g., +34623226544)

    Returns:
        Tuple of (exists: bool, customer: Customer | None)
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
                exc_info=True,
            )
            return (False, None)


# ============================================================================
# T-011: Graph Node Implementations
# ============================================================================


async def preprocess_node(state: ConversationState) -> dict[str, Any]:
    """
    Preprocess incoming message: add to history, check customer, detect first interaction.

    This node REPLACES the old process_incoming_message. It:
    1. Detects is_first_interaction (before adding message)
    2. Adds user message to state via add_message()
    3. Checks if customer exists in DB (without creating)
    4. Populates customer_id, customer_name if returning customer
    5. Sets is_first_interaction flag
    6. Sets last_node = "preprocess"

    Args:
        state: Current conversation state (checkpoint loaded by LangGraph)

    Returns:
        Partial state update dict for LangGraph reducers.
    """
    conversation_id = state.get("conversation_id", "unknown")
    user_message = state.get("user_message")

    if not user_message:
        logger.warning(
            "preprocess_node called without user_message | conversation_id=%s",
            conversation_id,
        )
        return {"last_node": "preprocess"}

    # Detect first interaction BEFORE adding message (empty = first turn)
    existing_messages = state.get("messages", [])
    is_first_interaction = len(existing_messages) == 0

    logger.info(
        "preprocess_node | conversation_id=%s | is_first=%s | msg_preview=%s",
        conversation_id,
        is_first_interaction,
        user_message[:50],
    )

    # Add user message to conversation history (returns partial dict)
    msg_update = add_message(state, "user", user_message)

    # Build the partial update
    updates: dict[str, Any] = {
        **msg_update,
        "is_first_interaction": is_first_interaction,
        "user_message": None,  # Clear transient field after processing
        "last_node": "preprocess",
    }

    # Check customer existence in DB
    customer_phone = state.get("customer_phone")
    if customer_phone:
        try:
            customer_exists, customer = await check_customer_exists(customer_phone)

            if customer_exists and customer:
                # Returning customer — load their data, skip GREETING
                updates["customer_id"] = str(customer.id)
                updates["customer_name"] = customer.first_name
                logger.info(
                    "preprocess_node: returning customer | conversation_id=%s | "
                    "customer_id=%s | name=%s",
                    conversation_id,
                    customer.id,
                    customer.first_name,
                )
            else:
                # New customer — GREETING mode will collect the name
                logger.info(
                    "preprocess_node: new customer | conversation_id=%s",
                    conversation_id,
                )

        except Exception as e:
            logger.error(
                "preprocess_node: customer check failed | conversation_id=%s | error=%s",
                conversation_id,
                e,
            )
            # Do not crash — continue without customer data

    return updates


async def router_node(state: ConversationState) -> dict[str, Any]:
    """
    Classify intent and determine which mode to activate.

    Routing logic (priority order):
    1. is_first_interaction=True OR customer_name is None → GREETING
    2. error_count >= threshold → ESCALATION (auto-escalation)
    3. escalation_triggered=True → ESCALATION (already escalated)
    4. Current mode is BOOKING and intent is not cancel/reject → stay BOOKING
    5. intent=book → BOOKING
    6. intent=escalate → ESCALATION
    7. intent=greet and NOT in BOOKING → GREETING
    8. Everything else → GENERAL

    Args:
        state: Current conversation state (after preprocess_node)

    Returns:
        Partial state update dict with updated current_mode.
    """
    conversation_id = state.get("conversation_id", "unknown")
    current_mode = state.get("current_mode") or "GREETING"
    customer_name = state.get("customer_name")
    is_first_interaction = state.get("is_first_interaction", False)
    error_count = state.get("error_count", 0)
    escalation_triggered = state.get("escalation_triggered", False)

    # Get messages to find user's last message
    messages = state.get("messages", [])
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

    # ── Rule 1: Already escalated — stay in ESCALATION ────────────────────────
    if escalation_triggered:
        logger.info(
            "router_node: escalation already triggered — ESCALATION | "
            "conversation_id=%s",
            conversation_id,
        )
        return {
            "current_mode": "ESCALATION",
            "last_node": "router",
        }

    # ── Rule 2: Auto-escalation threshold ─────────────────────────────────────
    if error_count >= AUTO_ESCALATION_THRESHOLD:
        logger.warning(
            "router_node: auto-escalation (error_count=%d) | conversation_id=%s",
            error_count,
            conversation_id,
        )
        return {
            "current_mode": "ESCALATION",
            "last_node": "router",
        }

    # ── Rule 3: First interaction or name unknown → GREETING ──────────────────
    if is_first_interaction or not customer_name:
        logger.info(
            "router_node: first interaction or no name → GREETING | "
            "conversation_id=%s",
            conversation_id,
        )
        return {
            "current_mode": "GREETING",
            "last_node": "router",
        }

    # ── Classify intent (keyword + LLM hybrid) ────────────────────────────────
    intent_router = _get_intent_router()
    try:
        intent: IntentResult = await intent_router.classify(
            text=user_message,
            current_mode=current_mode,
        )
    except Exception as exc:
        logger.error(
            "router_node: intent classification failed | conversation_id=%s | error=%s",
            conversation_id,
            exc,
        )
        # Default to current mode on classification failure
        intent = IntentResult(
            intent="ambiguous",
            confidence=0.0,
            raw_input=user_message,
            mode_hint=None,
        )

    logger.info(
        "router_node: intent classified | conversation_id=%s | intent=%s | "
        "confidence=%.2f | mode_hint=%s",
        conversation_id,
        intent.intent,
        intent.confidence,
        intent.mode_hint,
    )

    # Store intent in mode_context for downstream mode nodes
    intent_data = {
        "last_intent": intent.intent,
        "last_intent_confidence": intent.confidence,
    }

    # ── Rule 4: Escalation intent → ESCALATION ────────────────────────────────
    if intent.intent == "escalate":
        return {
            **transition_mode(state, "ESCALATION"),
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # ── Rule 5: Current mode is BOOKING and not a cancel ─────────────────────
    # Stay in BOOKING unless user explicitly cancels/rejects
    if current_mode == "BOOKING" and intent.intent not in ("cancel", "reject"):
        return {
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # ── Rule 6: Book intent → BOOKING ─────────────────────────────────────────
    if intent.intent == "book":
        mode_updates = transition_mode(state, "BOOKING")
        return {
            **mode_updates,
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # ── Rule 7: Greet intent → GREETING (only if not already past greeting) ──
    # Only route to GREETING on greet intent if we're coming from GENERAL or
    # haven't established the mode yet (avoids infinite greeting loops)
    if intent.intent == "greet" and current_mode not in ("BOOKING",):
        # Only go to GREETING if name is still unknown
        # If name is known, GREETING mode will immediately redirect to GENERAL
        return {
            "current_mode": "GREETING",
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    # ── Default: GENERAL mode ─────────────────────────────────────────────────
    # Handles: ask_info, confirm, reject (when not in BOOKING), ambiguous
    target_mode = "GENERAL"
    if current_mode == "BOOKING" and intent.intent in ("cancel", "reject"):
        # Staying in BOOKING to handle the cancel — BookingMode manages this
        target_mode = "BOOKING"

    if target_mode != current_mode:
        mode_updates = transition_mode(state, target_mode)
        return {
            **mode_updates,
            "mode_context": {**intent_data},
            "last_node": "router",
        }

    return {
        "mode_context": {**intent_data},
        "last_node": "router",
    }


def mode_dispatcher(state: ConversationState) -> str:
    """
    Conditional edge function: maps current_mode → node name.

    This is NOT a node — it's a LangGraph conditional edge function called
    after router_node to determine which mode node to dispatch to.

    Args:
        state: Current state (after router_node has set current_mode)

    Returns:
        Node name string (one of: "greeting", "general", "booking", "escalation")
    """
    current_mode = state.get("current_mode") or "GENERAL"

    mode_to_node: dict[str, str] = {
        "GREETING": "greeting",
        "GENERAL": "general",
        "BOOKING": "booking",
        "ESCALATION": "escalation",
    }

    node_name = mode_to_node.get(current_mode, "general")

    logger.info(
        "mode_dispatcher: current_mode=%s → node=%s | conversation_id=%s",
        current_mode,
        node_name,
        state.get("conversation_id", "unknown"),
    )

    return node_name


async def greeting_node(state: ConversationState) -> dict[str, Any]:
    """
    Handle GREETING mode — first contact and name extraction.

    Instantiates GreetingMode and delegates to handle().
    The LLM client is created fresh per call.

    Args:
        state: Current conversation state

    Returns:
        Partial state update from GreetingMode.handle()
    """
    conversation_id = state.get("conversation_id", "unknown")
    logger.info("greeting_node | conversation_id=%s", conversation_id)

    llm = _get_llm_client()
    mode = GreetingMode(tools=[], llm_client=llm)

    # Build a dummy IntentResult from mode_context
    mode_context = state.get("mode_context") or {}
    intent = IntentResult(
        intent=mode_context.get("last_intent", "greet"),
        confidence=mode_context.get("last_intent_confidence", 0.9),
        raw_input="",
        mode_hint="GREETING",
    )

    result = await mode.handle(state=state, intent=intent)
    return {**result, "last_node": "greeting"}


async def general_node(state: ConversationState) -> dict[str, Any]:
    """
    Handle GENERAL mode — FAQs, service info, informational queries.

    Instantiates GeneralMode and delegates to handle().
    GeneralMode uses an agentic loop with query_info and search_services tools.

    Args:
        state: Current conversation state

    Returns:
        Partial state update from GeneralMode.handle()
    """
    conversation_id = state.get("conversation_id", "unknown")
    logger.info("general_node | conversation_id=%s", conversation_id)

    llm = _get_llm_client()
    mode = GeneralMode(tools=[], llm_client=llm)

    # Build IntentResult from mode_context
    mode_context = state.get("mode_context") or {}
    intent = IntentResult(
        intent=mode_context.get("last_intent", "ask_info"),
        confidence=mode_context.get("last_intent_confidence", 0.8),
        raw_input="",
        mode_hint="GENERAL",
    )

    result = await mode.handle(state=state, intent=intent)
    return {**result, "last_node": "general"}


async def booking_node(state: ConversationState) -> dict[str, Any]:
    """
    Handle BOOKING mode — multi-step appointment booking flow.

    Instantiates BookingMode and delegates to handle().
    BookingMode uses the full tool set and manages booking sub-steps
    via mode_context["booking_step"].

    Args:
        state: Current conversation state

    Returns:
        Partial state update from BookingMode.handle()
    """
    conversation_id = state.get("conversation_id", "unknown")
    logger.info("booking_node | conversation_id=%s", conversation_id)

    llm = _get_llm_client()
    mode = BookingMode(tools=[], llm_client=llm)

    # Build IntentResult from mode_context
    mode_context = state.get("mode_context") or {}
    intent = IntentResult(
        intent=mode_context.get("last_intent", "book"),
        confidence=mode_context.get("last_intent_confidence", 0.8),
        raw_input="",
        mode_hint="BOOKING",
    )

    result = await mode.handle(state=state, intent=intent)
    return {**result, "last_node": "booking"}


async def escalation_node(state: ConversationState) -> dict[str, Any]:
    """
    Handle ESCALATION mode — human handoff.

    Instantiates EscalationMode and delegates to handle().
    EscalationMode calls escalate_to_human tool directly and sets
    escalation_triggered=True.

    Args:
        state: Current conversation state

    Returns:
        Partial state update from EscalationMode.handle()
    """
    conversation_id = state.get("conversation_id", "unknown")
    logger.info("escalation_node | conversation_id=%s", conversation_id)

    llm = _get_llm_client()
    mode = EscalationMode(tools=[], llm_client=llm)

    # Build IntentResult from mode_context
    mode_context = state.get("mode_context") or {}
    intent = IntentResult(
        intent=mode_context.get("last_intent", "escalate"),
        confidence=mode_context.get("last_intent_confidence", 1.0),
        raw_input="",
        mode_hint="ESCALATION",
    )

    result = await mode.handle(state=state, intent=intent)
    return {**result, "last_node": "escalation"}


async def summarize_node(state: ConversationState) -> dict[str, Any]:
    """
    Summarize conversation when message count threshold is reached.

    Wraps the existing summarize_conversation function from agent/nodes/summarization.py.
    FIFO windowing keeps recent 10 messages, summarizing older ones.

    The summarization is a no-op if should_summarize() returns False,
    preserving the existing logic without changes.

    Args:
        state: Current conversation state

    Returns:
        Updated state (from summarize_conversation) with last_node set.
    """
    conversation_id = state.get("conversation_id", "unknown")
    logger.debug("summarize_node | conversation_id=%s", conversation_id)

    # Reuse existing summarization logic (handles its own should_summarize check)
    result = await summarize_conversation(state)

    # If result is the full state (not a dict subset), extract relevant updates
    if isinstance(result, dict):
        return {**result, "last_node": "summarize"}

    return {"last_node": "summarize"}


# ============================================================================
# Graph Construction
# ============================================================================


def create_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    Create and compile the v6.0 mode-based conversation StateGraph.

    Graph structure:
        START → preprocess → router → mode_dispatcher
            → [greeting | general | booking | escalation] → summarize → END

    Args:
        checkpointer: Optional checkpoint saver for state persistence.
                      If None, no checkpointing is performed (useful for testing).
                      For production, pass a RedisSaver instance.

    Returns:
        Compiled StateGraph ready for invocation.

    Example:
        >>> from agent.state.checkpointer import get_redis_checkpointer
        >>> checkpointer = get_redis_checkpointer()
        >>> graph = create_graph(checkpointer=checkpointer)
        >>> config = {"configurable": {"thread_id": "wa-msg-123"}}
        >>> result = await graph.ainvoke(initial_state, config=config)
    """
    graph = StateGraph(ConversationState)

    # ========================================================================
    # Nodes
    # ========================================================================
    graph.add_node("preprocess", preprocess_node)
    graph.add_node("router", router_node)
    graph.add_node("greeting", greeting_node)
    graph.add_node("general", general_node)
    graph.add_node("booking", booking_node)
    graph.add_node("escalation", escalation_node)
    graph.add_node("summarize", summarize_node)

    # ========================================================================
    # Edges
    # ========================================================================

    # Entry point
    graph.set_entry_point("preprocess")

    # preprocess → router (always)
    graph.add_edge("preprocess", "router")

    # router → mode node (conditional based on current_mode)
    graph.add_conditional_edges(
        "router",
        mode_dispatcher,
        {
            "greeting": "greeting",
            "general": "general",
            "booking": "booking",
            "escalation": "escalation",
        },
    )

    # All mode nodes → summarize → END
    graph.add_edge("greeting", "summarize")
    graph.add_edge("general", "summarize")
    graph.add_edge("booking", "summarize")
    graph.add_edge("escalation", "summarize")
    graph.add_edge("summarize", END)

    # ========================================================================
    # Compile
    # ========================================================================
    logger.info("Compiling v6.0 mode-based conversation graph")
    compiled_graph = graph.compile(checkpointer=checkpointer)
    logger.info("v6.0 conversation graph compiled successfully")

    return compiled_graph


# ============================================================================
# Backward compatibility alias
# ============================================================================

def create_conversation_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    Backward-compatible alias for create_graph().

    Used by agent/main.py during the transition period.
    Will be removed once main.py is fully updated to use create_graph().
    """
    return create_graph(checkpointer=checkpointer)


# Legacy export used by old main.py imports
def MAITE_SYSTEM_PROMPT() -> str:
    """Legacy stub — no longer used in v6.0. Returns empty string."""
    logger.warning(
        "MAITE_SYSTEM_PROMPT() called — this is a legacy stub in v6.0. "
        "System prompts are now embedded in each mode node."
    )
    return ""
