"""
Greeting Mode — v6.0 Mode-Based Architecture (M3 create_agent migration).

Pure welcome + menu presenter. This mode NEVER asks for the customer's name,
performs no customer lookup or creation, and never uses any name in responses.

Flow:
1. Extract any booking-content hints from the greeting message.
2. Determine target mode: BOOKING if booking content detected, else GENERAL.
3. Render a welcome message (LLM via ``create_agent`` + fallback).
4. Transition to the target mode.

Target mode after greeting is determined by ``last_intent`` in mode_context:
- ``"book"`` / ``"reschedule"`` → BOOKING
- otherwise → GENERAL (default)
- Deterministic override: if the user message contains booking-intent tokens
  (F-9), BOOKING wins regardless of the intent classifier output.

NO name in any response. NO DB writes. NO customer creation.

M3 changes: the legacy ``BaseModeNode`` subclass is gone. The public surface
is now ``build_greeting_node(llm_factory)`` which returns an async LangGraph
node function, plus the original module-level helpers (still imported by
``conversation_flow.py`` and the test suite).
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any, Callable

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, SystemMessage

from agent.middleware.token_tracking import TokenTrackingMiddleware
from agent.modes._intro import FIRST_TURN_INTRO, maybe_prepend_intro
from agent.prompts.loader import build_layered_messages
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode
from shared.audience_maps import AUDIENCE_HINT_MAP
from shared.config import get_settings

logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────────────

# Pre-defined greeting messages (ALL name-free)
_WELCOME_NEW = "¿En qué te puedo ayudar?"
_WELCOME_RETURNING = "¡Hola de nuevo! 😊 ¿En qué te puedo ayudar?"

# Tokens that signal booking intent in the greeting message (F-9).
_BOOKING_CONTENT_TOKENS: frozenset[str] = frozenset(
    {
        # People / gender / audience
        "mujer",
        "hombre",
        "nino",
        "nina",
        "dama",
        "caballero",
        "adulta",
        "adulto",
        # Action verbs / booking intent
        "turno",
        "reservar",
        "reserva",
        "cita",
        "quiero",
        "necesito",
        "queria",
        # Services
        "corte",
        "tinte",
        "color",
        "mechas",
        "peinado",
        "manicura",
        "barba",
        "peluqueria",
    }
)


# ── Pure helpers (kept as module-level functions so tests import them) ─────


def _normalize_text(text: str | None) -> str:
    """Normalize text for comparison: strip, lowercase, remove accents."""
    if not text:
        return ""
    raw = text.strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _has_booking_content(message: str | None) -> bool:
    """Return True when the message contains tokens that signal a service request."""
    if not message:
        return False
    normalized = _normalize_text(message)
    return any(token in normalized for token in _BOOKING_CONTENT_TOKENS)


def _build_booking_handoff_context(message: str | None) -> dict:
    """Build a booking handoff context dict from a greeting message."""
    if not message:
        return {}
    if not _has_booking_content(message):
        return {}

    ctx: dict = {"opening_booking_request": message}

    normalized = _normalize_text(message)
    for token, hint in AUDIENCE_HINT_MAP.items():
        if token in normalized:
            ctx["service_audience_hint"] = hint
            break

    return ctx


def _resolve_target_mode(mode_context: dict, has_booking_content: bool = False) -> str:
    """Determine which mode to transition to after the greeting (ADR-4 / F-9)."""
    last_intent = (mode_context or {}).get("last_intent", "greet")
    if last_intent in ("book", "reschedule"):
        return "BOOKING"
    if has_booking_content:
        return "BOOKING"
    return "GENERAL"


# ── create_agent integration ────────────────────────────────────────────────


def _use_optimized_prompts() -> bool:
    """Return True when the layered-prompt assembly is enabled.

    When False (or when settings can't be loaded), we short-circuit and use
    the canned welcome string instead of calling the LLM — matches the
    legacy BaseModeNode behaviour.
    """
    try:
        return bool(get_settings().USE_OPTIMIZED_PROMPTS)
    except Exception:
        return True


def _extract_final_text(result: Any) -> str:
    """Extract the final assistant message content from an agent result dict."""
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages") or []
    # The agent's final response is the last AIMessage in the stream.
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return "\n".join(parts).strip()
    return ""


async def _generate_welcome_response(
    llm: Any,
    state: ConversationState,
    mode_context: dict,
    fallback: str,
) -> str:
    """Run the greeting ``create_agent`` once and return the final assistant text.

    GREETING has NO tools and NO tool_choice — the agent is effectively a
    single-shot LLM call wrapped in ``TokenTrackingMiddleware``. On any
    failure we fall back to the canned welcome string.
    """
    if llm is None or not _use_optimized_prompts():
        return fallback

    try:
        messages, _ = await build_layered_messages(
            state,
            mode_context,
            include_history=True,
            history_limit=6,
            mode_name="GREETING",
            include_catalog=False,
        )
    except Exception as exc:
        logger.warning("GreetingMode: build_layered_messages failed: %s — using fallback", exc)
        return fallback

    # Pull every SystemMessage into a single system_prompt string. create_agent
    # accepts ``system_prompt`` + user/tool messages separately, so we collapse
    # the layered SystemMessages into one block and pass the remaining
    # Human/AI messages as the agent input.
    system_parts: list[str] = []
    transcript: list = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content:
                system_parts.append(content)
        else:
            transcript.append(msg)
    system_prompt = "\n\n".join(system_parts)

    try:
        agent = create_agent(
            model=llm,
            tools=[],
            system_prompt=system_prompt,
            middleware=[TokenTrackingMiddleware(mode_name="GREETING")],
        )
        result = await agent.ainvoke({"messages": transcript})
    except Exception as exc:
        logger.warning("GreetingMode: create_agent invocation failed: %s — using fallback", exc)
        return fallback

    text = _extract_final_text(result)
    return text or fallback


def _build_booking_context_update(
    booking_handoff: dict,
    mode_context: dict,
) -> dict:
    """Assemble the partial ``booking_context`` update from handoff + hints."""
    booking_ctx_update: dict = {}
    if booking_handoff:
        if booking_handoff.get("opening_booking_request"):
            booking_ctx_update["opening_booking_request"] = booking_handoff[
                "opening_booking_request"
            ]
        if booking_handoff.get("service_audience_hint"):
            booking_ctx_update["service_audience_hint"] = booking_handoff[
                "service_audience_hint"
            ]
    hints = mode_context.get("booking_hints") or {}
    if hints.get("preferred_stylist_name"):
        booking_ctx_update["preferred_stylist_name"] = hints["preferred_stylist_name"]
    if hints.get("preferred_date_hint"):
        booking_ctx_update["preferred_date_hint"] = hints["preferred_date_hint"]
    return booking_ctx_update


async def _handle_greeting(
    state: ConversationState,
    llm: Any,
) -> dict:
    """Compute the state update for a greeting turn.

    Mirrors the old ``GreetingMode.handle`` contract:
    - Returning customer (``customer_name`` set) → warm returning greeting.
    - New customer → neutral welcome, NO DB writes, NO name collection.
    - Booking content detected → transition to BOOKING + booking_context hints.
    """
    conversation_id = state.get("conversation_id", "unknown")
    customer_name = state.get("customer_name")
    mode_context = state.get("mode_context") or {}
    is_first = state.get("is_first_interaction", True)

    logger.info(
        "GreetingMode.handle | conversation=%s | customer_name=%s | is_first=%s",
        conversation_id,
        customer_name,
        is_first,
    )

    # Extract booking handoff from the user's greeting message
    last_user_message = ""
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "user":
            last_user_message = msg.get("content", "")
            break

    booking_handoff = _build_booking_handoff_context(last_user_message)
    has_booking_content = bool(booking_handoff)
    target_mode = _resolve_target_mode(mode_context, has_booking_content=has_booking_content)

    fallback = _WELCOME_RETURNING if customer_name else _WELCOME_NEW
    response = await _generate_welcome_response(llm, state, mode_context, fallback=fallback)
    final_response, disclosure_sent = maybe_prepend_intro(response, state)

    transition_update = transition_mode(state, target_mode)

    if has_booking_content and target_mode == "BOOKING":
        booking_ctx_update = _build_booking_context_update(booking_handoff, mode_context)
        if booking_ctx_update:
            transition_update["booking_context"] = booking_ctx_update

    updates: dict = {
        **transition_update,
        **add_message(state, "assistant", final_response),
        "user_message": None,
    }
    if disclosure_sent:
        updates["ai_disclosure_sent"] = True

    if customer_name:
        logger.info(
            "GreetingMode: returning customer → %s",
            target_mode,
        )
    else:
        logger.info(
            "GreetingMode: new customer → %s",
            target_mode,
        )
    return updates


# ── Public factory used by conversation_flow.create_graph ──────────────────


def build_greeting_node(
    llm_factory: Callable[[], Any] | None = None,
) -> Callable[[ConversationState], Any]:
    """Return an async LangGraph node function for the GREETING mode.

    Args:
        llm_factory: Zero-arg callable that returns a ``BaseChatModel``
            instance. Invoked lazily on every turn so tests can swap the
            factory per graph build. When ``None`` the node falls back to
            the canned welcome string (matches legacy behaviour on
            misconfigured deployments).

    Returns:
        ``async def greeting_node(state) -> dict`` — LangGraph-compatible
        node that reads the active intent from ``state["mode_context"]``
        and returns a partial state update dict. ``last_node`` is set to
        ``"greeting"`` by the caller in ``conversation_flow.create_graph``.
    """

    async def greeting_node(state: ConversationState) -> dict:
        llm = llm_factory() if llm_factory is not None else None
        return await _handle_greeting(state, llm)

    return greeting_node


__all__ = [
    "FIRST_TURN_INTRO",
    "_BOOKING_CONTENT_TOKENS",
    "_WELCOME_NEW",
    "_WELCOME_RETURNING",
    "_build_booking_handoff_context",
    "_has_booking_content",
    "_normalize_text",
    "_resolve_target_mode",
    "build_greeting_node",
]
