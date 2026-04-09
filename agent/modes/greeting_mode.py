"""
Greeting Mode — v6.0 Mode-Based Architecture (scope-realignment refactor).

Pure welcome + menu presenter. This mode NEVER asks for the customer's name,
performs no customer lookup or creation, and never uses any name in responses.

Flow:
1. Extract any booking-content hints from the greeting message.
2. Determine target mode: BOOKING if booking content detected, else GENERAL.
3. Render a static (or layered) welcome message.
4. Transition to the target mode.

Target mode after greeting is determined by `last_intent` in mode_context:
- "book" → BOOKING (user greeted AND wants to book)
- "ask_info" → GENERAL (user greeted AND has a question)
- anything else → GENERAL (default)

NO name in any response. NO DB writes. NO customer creation.
"""

import logging
import unicodedata

from agent.modes.base import BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode
from shared.audience_maps import AUDIENCE_HINT_MAP

logger = logging.getLogger(__name__)

# Pre-defined greeting messages (ALL name-free)
# FIX: Removed FIRST_TURN_INTRO from _WELCOME_NEW to avoid duplication.
# FIRST_TURN_INTRO is prepended automatically by BaseModeNode._maybe_prepend_intro() (base.py:257)
_WELCOME_NEW = "¿En qué te puedo ayudar?"
_WELCOME_RETURNING = "¡Hola de nuevo! 😊 ¿En qué te puedo ayudar?"

# ── ADR-4: Audience hint tokens — imported from shared.audience_maps ─────────

# Tokens that signal booking intent in the greeting message.
# F-9: These tokens are used both for booking handoff context AND for
# deterministic BOOKING transition override in _resolve_target_mode().
_BOOKING_CONTENT_TOKENS: frozenset[str] = frozenset(
    {
        # People / gender / audience (from AUDIENCE_HINT_MAP)
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
        "queria",  # "quería" normalized → no accent
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


def _normalize_text(text: str | None) -> str:
    """Normalize text for comparison: strip, lowercase, remove accents."""
    if not text:
        return ""
    raw = text.strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _has_booking_content(message: str | None) -> bool:
    """
    Return True when the message contains tokens that signal a service request.

    Used to detect when a greeting message also carries booking intent
    (e.g. "Hola, quiero un corte de dama") so the booking context can be
    passed to the next mode even when the router classified it as "greet".

    Args:
        message: Raw user message text (or None).

    Returns:
        True if any booking-intent token is found in the normalized text.
    """
    if not message:
        return False
    normalized = _normalize_text(message)
    return any(token in normalized for token in _BOOKING_CONTENT_TOKENS)


def _build_booking_handoff_context(message: str | None) -> dict:
    """
    Build a booking handoff context dict from a greeting message.

    Extracts:
    - opening_booking_request: the original message text (for intent carry-over)
    - service_audience_hint: audience classification based on keywords

    Args:
        message: Raw user message text (or None).

    Returns:
        Dict with extracted booking context keys, or empty dict if no content.
    """
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
    """
    Determine which mode to transition to after the greeting.

    ADR-4 / F-9: Widened gate — routes to BOOKING when:
    - last_intent == "book" or "reschedule" (LLM intent router result), OR
    - has_booking_content is True (deterministic keyword detection override)

    F-9 rationale: when the user's first message contains clear booking content
    (service names, booking verbs, audience tokens), we force BOOKING regardless
    of the intent router's classification. This reduces LLM-compliance dependency
    on the critical first-turn routing decision.

    Args:
        mode_context: Current mode context dict from ConversationState.
        has_booking_content: True when booking-intent tokens were detected in
            the user's greeting message by _has_booking_content().

    Returns:
        "BOOKING" if last_intent == "book"/"reschedule" OR has_booking_content,
        "GENERAL" otherwise (including greet, ask_info, ambiguous, etc.)
    """
    last_intent = (mode_context or {}).get("last_intent", "greet")
    if last_intent in ("book", "reschedule"):
        return "BOOKING"
    # F-9: Deterministic override — booking content detected in first message
    if has_booking_content:
        return "BOOKING"
    return "GENERAL"


class GreetingMode(BaseModeNode):
    """
    Mode node for first-contact greetings.

    Responsibilities:
    - Send a warm welcome on genuine greeting turns (name-free)
    - Detect booking-intent content in the greeting and carry it over
    - Transition to the appropriate mode based on detected intent (BOOKING or GENERAL)

    NO customer creation. NO name collection. NO DB writes.
    Customer creation happens atomically inside book() when the user confirms.
    """

    @property
    def mode_name(self) -> str:
        return "GREETING"

    def get_tools(self):
        return []

    @staticmethod
    def _extract_response_text(result: object | None) -> str:
        if result is None:
            return ""
        content = getattr(result, "content", result)
        return str(content).strip()

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle the greeting flow.

        Two branches, both name-free:
        1. Returning customer (customer_name exists) → warm greeting → target mode
        2. New customer → warm greeting → target mode (NO DB writes)

        ADR-4: Booking content in greeting message is detected and carried over to the
               transition mode_context via _build_booking_handoff_context().

        NEVER mentions the customer's name in any response.
        NEVER creates a customer record — that happens inside book().

        Args:
            state: Current conversation state
            intent: IntentResult (not used in GREETING — simple sequential flow)

        Returns:
            Partial state update dict
        """
        conversation_id = state.get("conversation_id", "unknown")
        customer_name = state.get("customer_name")
        mode_context = state.get("mode_context") or {}
        is_first = state.get("is_first_interaction", True)

        self.logger.info(
            "GreetingMode.handle | conversation=%s | customer_name=%s | is_first=%s",
            conversation_id,
            customer_name,
            is_first,
        )

        # ADR-4: Extract booking handoff context from the user's greeting message
        # (e.g. "Hola, quiero turno para un caballero" → service_audience_hint = adult_male)
        last_user_message = ""
        for msg in reversed(state.get("messages", [])):
            if msg.get("role") == "user":
                last_user_message = msg.get("content", "")
                break

        booking_handoff = _build_booking_handoff_context(last_user_message)
        has_booking_content = bool(booking_handoff)

        # F-9: Pass has_booking_content so booking content forces BOOKING transition
        target_mode = _resolve_target_mode(mode_context, has_booking_content=has_booking_content)

        # ── Branch 1: Returning customer (name already known) ────────────
        if customer_name:
            self.logger.info(
                "GreetingMode: returning customer (name=%s), transitioning to %s",
                customer_name,
                target_mode,
            )
            fallback_response = _WELCOME_RETURNING
            response = await self._render_layered_response(
                state,
                mode_context,
                fallback_response=fallback_response,
                step_name="returning_customer",
                include_history=False,
            )
            final_response, disclosure_sent = self._maybe_prepend_intro(response, state)
            transition_update = transition_mode(state, target_mode)

            # ADR-4: Inject booking handoff context into the new mode_context
            if has_booking_content and booking_handoff:
                new_mode_ctx = {**transition_update.get("mode_context", {}), **booking_handoff}
                transition_update["mode_context"] = new_mode_ctx

            # P4: Forward booking_hints from router (first-interaction booking) to BOOKING mode
            booking_hints_from_router = mode_context.get("booking_hints")
            if booking_hints_from_router and target_mode == "BOOKING":
                new_mode_ctx = {**transition_update.get("mode_context", {})}
                new_mode_ctx.update(booking_hints_from_router)
                transition_update["mode_context"] = new_mode_ctx

            updates = {
                **transition_update,
                **add_message(state, "assistant", final_response),
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── Branch 2: New customer ───────────────────────────────────────
        # Customer creation happens inside book() tool. GREETING does nothing
        # to the DB — just render a welcome and transition to target mode.
        self.logger.info(
            "GreetingMode: new customer | target_mode=%s",
            target_mode,
        )

        fallback_response = _WELCOME_NEW
        response = await self._render_layered_response(
            state,
            mode_context,
            fallback_response=fallback_response,
            step_name="welcome",
            include_history=False,
        )
        final_response, disclosure_sent = self._maybe_prepend_intro(response, state)
        transition_update = transition_mode(state, target_mode)

        # ADR-4: Inject booking handoff context into the new mode_context
        if has_booking_content and booking_handoff:
            new_mode_ctx = {**transition_update.get("mode_context", {}), **booking_handoff}
            transition_update["mode_context"] = new_mode_ctx

        # P4: Forward booking_hints from router (first-interaction booking) to BOOKING mode
        booking_hints_from_router = mode_context.get("booking_hints")
        if booking_hints_from_router and target_mode == "BOOKING":
            new_mode_ctx = {**transition_update.get("mode_context", {})}
            new_mode_ctx.update(booking_hints_from_router)
            transition_update["mode_context"] = new_mode_ctx

        updates = {
            **transition_update,
            **add_message(state, "assistant", final_response),
            "user_message": None,
        }
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True
        return updates

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _render_layered_response(
        self,
        state: ConversationState,
        mode_context: dict,
        *,
        fallback_response: str,
        step_name: str,
        include_history: bool = False,
    ) -> str:
        """Render a greeting response via layered prompts, falling back to hardcoded."""
        if not self._use_optimized_prompts():
            return fallback_response

        messages = await self._build_layered_messages(
            state,
            mode_context,
            step_name=step_name,
            include_history=include_history,
        )
        response_text = self._extract_response_text(await self._call_llm(messages))
        return response_text if response_text else fallback_response
