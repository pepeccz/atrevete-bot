"""
GreetingMode — Handles first interactions and name confirmation (v6.0).

This mode FIXES the infinite loop bug from v5.x where `process_incoming_message`
would re-set `name_confirmation_pending=True` on every message, causing the bot to
keep asking for the customer's name in an endless loop.

Root cause of the bug:
    - The old FSM would reset `name_confirmation_pending=True` on every incoming
      message because the customer was never created until after name confirmation.
    - The new mode-based architecture tracks state in `current_mode` + `customer_name`
      fields with `preserve_if_none` reducers, so once the name is set it NEVER resets.

Anti-loop guarantee:
    - Once `state.customer_name` is set, GreetingMode IMMEDIATELY transitions to
      GENERAL mode. It NEVER asks for the name again.
    - The mode only stays in GREETING until `customer_name` is populated. After that,
      any GREETING mode entry short-circuits to GENERAL.

Flow:
    Turn 1 (is_first_interaction=True):
        → Generate welcome message + ask for name
        → Set is_first_interaction=False
        → Stay in GREETING

    Turn 2 (customer_name is None, user just replied):
        → Extract name from user_message
        → Generate "¡Perfecto, {name}! ¿En qué puedo ayudarte?" response
        → Set customer_name={name}
        → Transition to GENERAL

    Turn N (customer_name is already set):
        → Short-circuit: transition to GENERAL immediately
        → No message generated (orchestrator will re-dispatch to GENERAL)
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.modes.base import BaseModeNode
from agent.routing.intent_router import IntentResult
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)

# ============================================================================
# System prompt for name extraction (minimal, cheap LLM call)
# ============================================================================

_NAME_EXTRACT_SYSTEM = (
    "Eres un extractor de nombres. El usuario acaba de decir cómo se llama. "
    "Extrae SOLO el primer nombre o nombre completo que el usuario proporcionó. "
    "Responde ÚNICAMENTE con el nombre, sin puntuación ni explicación. "
    "Si no puedes detectar un nombre claro, responde con: UNKNOWN"
)

# Welcome message templates (no LLM needed — hardcoded to save cost on first turn)
_WELCOME_NEEDS_NAME = (
    "¡Hola! 🌸 Soy Maite, la asistenta virtual de Atrévete Peluquería. "
    "¿Con quién tengo el gusto de hablar?"
)

_WELCOME_WITH_HINT = (
    "¡Hola! 🌸 Soy Maite, la asistenta virtual de Atrévete Peluquería. "
    "Por lo que me ha llegado te llamas *{name}*, ¿es correcto?"
)

_WELCOME_RETURNING = "¡Hola de nuevo, {name}! 😊 ¿En qué puedo ayudarte hoy?"

# ============================================================================
# Non-name words filter
# ============================================================================
# Words that look like names when extracted but are clearly NOT names.
# Applied to heuristic and LLM results before accepting a name.
#
# Categories:
#   - Affirmatives: user is confirming/agreeing, not giving their name
#   - Negatives: user is declining, not giving their name
#   - Greetings: standalone greetings aren't names
#
# Normalised to lowercase. Accent-stripped variants are included explicitly
# because `str.lower()` alone doesn't strip accents.
_NON_NAME_WORDS: frozenset[str] = frozenset(
    {
        # Affirmatives
        "si",
        "sí",
        "yes",
        "ok",
        "okay",
        "bueno",
        "dale",
        "claro",
        "claro que si",
        "claro que sí",
        "por supuesto",
        "correcto",
        "exacto",
        "exactamente",
        "de acuerdo",
        "perfecto",
        "genial",
        "bien",
        "esta bien",
        "está bien",
        # Negatives
        "no",
        "nope",
        "negativo",
        "para nada",
        # Greetings (standalone)
        "hola",
        "hey",
        "buenas",
        "buenos días",
        "buenas tardes",
        "buenas noches",
        "saludos",
    }
)

# Minimum character length a candidate name must have.
# "Si", "Ok", "No" are all <= 2 chars — real names of length 2 exist (e.g. "Ai")
# but raising the floor to 2 chars (exclusive) catches the most common false positives
# without rejecting legitimate 3+-character names.
_MIN_NAME_LENGTH = 2


def _is_valid_name(candidate: str) -> bool:
    """
    Return True if *candidate* looks like a real person's name.

    Rejects:
    - Empty strings or whitespace-only strings.
    - Strings shorter than _MIN_NAME_LENGTH characters (after strip).
    - Strings whose normalised form is in _NON_NAME_WORDS (affirmatives, negatives,
      standalone greetings).

    Args:
        candidate: Raw string extracted by heuristic or LLM.

    Returns:
        True when the candidate is a plausible name; False otherwise.
    """
    stripped = candidate.strip()
    if not stripped:
        return False
    if len(stripped) <= _MIN_NAME_LENGTH:
        return False
    if stripped.lower() in _NON_NAME_WORDS:
        return False
    return True


class GreetingMode(BaseModeNode):
    """
    Mode node for the GREETING conversation phase.

    Handles:
    - First interaction welcome (hardcoded Spanish greeting, no LLM cost)
    - Name extraction from user response (LLM call, once per conversation)
    - Returning customer detection (immediate transition to GENERAL)

    Anti-loop invariant:
        Once `state["customer_name"]` is set, this mode NEVER asks for the name
        again. It immediately signals a transition to GENERAL mode.
    """

    @property
    def mode_name(self) -> str:
        return "GREETING"

    async def handle(
        self,
        state: ConversationState,
        intent: IntentResult,
    ) -> dict:
        """
        Process a turn in GREETING mode.

        Decision tree:
        1. customer_name already set → transition to GENERAL (no message)
        2. is_first_interaction=True → send welcome, ask for name
        3. Otherwise (second turn, user just gave name) → extract name, transition to GENERAL

        Args:
            state: Current ConversationState (read-only).
            intent: Classified intent from IntentRouter.

        Returns:
            Partial state update dict for LangGraph reducers.
        """
        conversation_id = state.get("conversation_id", "unknown")
        customer_name = state.get("customer_name")
        is_first = state.get("is_first_interaction", True)

        # ── Guard: name already known → short-circuit to GENERAL ──────────────
        # This is the core anti-loop guarantee.
        # If customer_name is set, we should never be asking for it again.
        if customer_name:
            logger.info(
                "GreetingMode: customer_name already set, transitioning to GENERAL | "
                "conversation_id=%s | name=%s",
                conversation_id,
                customer_name,
            )
            transition = transition_mode(state, "GENERAL")
            # Add a returning greeting
            response = _WELCOME_RETURNING.format(name=customer_name)
            msg_update = add_message(state, "assistant", response)
            return {**transition, **msg_update}

        # ── Turn 1: First interaction — send welcome, ask for name ─────────────
        if is_first:
            logger.info(
                "GreetingMode: first interaction — sending welcome | "
                "conversation_id=%s",
                conversation_id,
            )
            welcome_text = _WELCOME_NEEDS_NAME
            msg_update = add_message(state, "assistant", welcome_text)
            return {
                **msg_update,
                "is_first_interaction": False,
                # Stay in GREETING mode — next turn will extract the name
                "current_mode": "GREETING",
            }

        # ── Turn 2+: User has replied — extract name ───────────────────────────
        # We're in GREETING mode and customer_name is None, so the user just
        # responded to our "¿Con quién tengo el gusto de hablar?" question.
        user_message = state.get("user_message") or ""

        # Try to extract name from the user's message
        extracted_name = await self._extract_name(user_message)

        if extracted_name and extracted_name != "UNKNOWN":
            logger.info(
                "GreetingMode: name extracted | conversation_id=%s | name=%s",
                conversation_id,
                extracted_name,
            )
            response = f"¡Perfecto, {extracted_name}! 😊 ¿En qué puedo ayudarte hoy?"
            msg_update = add_message(state, "assistant", response)
            transition = transition_mode(state, "GENERAL")
            return {
                **transition,
                **msg_update,
                "customer_name": extracted_name,
            }
        else:
            # Could not extract a clear name — ask again politely
            logger.info(
                "GreetingMode: name extraction failed, asking again | "
                "conversation_id=%s | user_message=%s",
                conversation_id,
                user_message[:50],
            )
            response = "Disculpá, ¿me podrías decir tu nombre?"
            return add_message(state, "assistant", response)

    async def _extract_name(self, user_message: str) -> str:
        """
        Use LLM to extract the customer's name from their response.

        Falls back to a simple heuristic (first 1-2 words) if LLM call fails.

        Args:
            user_message: The user's text response to our name question.

        Returns:
            Extracted name string, or "UNKNOWN" if extraction failed.
        """
        if not user_message or not user_message.strip():
            return "UNKNOWN"

        # Simple heuristic fallback: if message is short (1-3 words), use it directly
        words = user_message.strip().split()
        if len(words) <= 3:
            # Short message — likely just the name (e.g., "Pedro", "Juan García")
            # Filter out common filler words
            filler_words = {
                "me", "llamo", "soy", "mi", "nombre", "es", "el", "la", "un", "una",
                "hola", "buenas", "hey",
            }
            name_words = [w for w in words if w.lower() not in filler_words]
            if name_words:
                # Capitalize first letter of each word
                name = " ".join(w.capitalize() for w in name_words[:2])
                if not _is_valid_name(name):
                    logger.debug(
                        "GreetingMode._extract_name: heuristic rejected non-name | "
                        "raw=%s → candidate=%s",
                        user_message[:50],
                        name,
                    )
                    return "UNKNOWN"
                logger.debug(
                    "GreetingMode._extract_name: heuristic | raw=%s → name=%s",
                    user_message[:50],
                    name,
                )
                return name

        # LLM extraction for more complex messages
        try:
            messages = [
                SystemMessage(content=_NAME_EXTRACT_SYSTEM),
                HumanMessage(content=user_message),
            ]
            result = await self._call_llm(messages)
            if result is None:
                logger.warning(
                    "GreetingMode._extract_name: LLM returned None, using heuristic"
                )
                return self._heuristic_extract(user_message)

            extracted = result.content.strip() if hasattr(result, "content") else str(result).strip()

            # Validate: should be a plausible name (not too long, not empty, not a
            # non-name word like "Sí" / "Ok" / "Dale").
            if extracted and extracted != "UNKNOWN" and len(extracted) <= 50:
                capitalized = extracted.capitalize()
                if _is_valid_name(capitalized):
                    return capitalized
                logger.debug(
                    "GreetingMode._extract_name: LLM returned non-name | extracted=%s",
                    extracted,
                )
                return "UNKNOWN"

            return "UNKNOWN"

        except Exception as exc:
            logger.warning(
                "GreetingMode._extract_name: LLM failed | error=%s | using heuristic",
                exc,
            )
            return self._heuristic_extract(user_message)

    def _heuristic_extract(self, user_message: str) -> str:
        """
        Simple heuristic name extraction fallback.

        Takes the first 1-2 meaningful words from the user message, filtering
        out common Spanish filler words.

        Args:
            user_message: Raw user message text.

        Returns:
            Extracted name string, or "UNKNOWN" if nothing plausible found.
        """
        filler_words = {
            "me", "llamo", "soy", "mi", "nombre", "es", "el", "la", "un", "una",
            "hola", "buenas", "hey", "que", "qué", "como", "cómo", "pues",
        }
        words = user_message.strip().split()
        name_words = [w for w in words if w.lower() not in filler_words][:2]

        if name_words:
            candidate = " ".join(w.capitalize() for w in name_words)
            if not _is_valid_name(candidate):
                return "UNKNOWN"
            return candidate

        return "UNKNOWN"
