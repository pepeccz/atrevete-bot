"""
Greeting Mode — v6.0 Mode-Based Architecture.

Handles first contact and customer name collection. This mode fires ONCE
per new customer (when is_first_interaction=True or customer_name is None).

Flow:
1. Turn 1 (is_first_interaction=True): Send welcome message, stay in GREETING
2. Turn 2+ (customer_name is None): Extract name from user message, create customer in DB,
   transition to GENERAL
3. Anti-loop: if customer_name already known, transition immediately to GENERAL

This design ensures the greeting loop can never trigger infinitely — once the
customer's name is set in state, GREETING will not repeat.
"""

import logging
import string

from langchain_core.messages import HumanMessage, SystemMessage
from agent.tools.customer_tools import manage_customer

from agent.modes.base import BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)

# Words that are clearly NOT names — used to filter false positives
_NON_NAME_WORDS: frozenset[str] = frozenset({
    "si", "sí", "yes", "ok", "okay", "bueno", "dale", "claro",
    "correcto", "exacto", "de acuerdo", "perfecto", "genial", "bien", "no", "nope",
    "hola", "hey", "buenas", "buenos días", "buenas tardes", "buenas noches",
    "gracias", "thanks", "por favor", "please",
})

# Minimum character length for a valid name candidate
_MIN_NAME_LENGTH = 2

# Filler words stripped before extracting the name candidate
_FILLER_WORDS: frozenset[str] = frozenset({
    "me", "llamo", "soy", "mi", "nombre", "es", "el", "la",
    "un", "una", "hola", "buenas", "hey", "buenos", "no",
})

# Pre-defined greeting messages
_WELCOME_NEEDS_NAME = (
    "¡Hola! 🌸 Soy Maite, la asistenta virtual de Atrévete Peluquería. "
    "¿Con quién tengo el gusto de hablar?"
)
_WELCOME_CONFIRM_SUGGESTED = (
    "¡Hola! 🌸 Soy Maite, la asistenta virtual de Atrévete Peluquería. "
    "¿Puedo llamarte {name}?"
)
_WELCOME_RETURNING = "¡Hola de nuevo, {name}! 😊 ¿En qué puedo ayudarte hoy?"
_ASK_NAME_AGAIN = "Disculpá, ¿me podrías decir tu nombre para poder atenderte mejor?"
_ASK_NAME_AFTER_REJECTION = "Perfecto, decime entonces cómo te gustaría que te llame."
_CONFIRMATION = "¡Perfecto, {name}! 😊 ¿En qué puedo ayudarte hoy?"


def _is_valid_name(candidate: str) -> bool:
    """Return True if the candidate string looks like a real name."""
    stripped = candidate.strip()
    if not stripped or len(stripped) <= _MIN_NAME_LENGTH:
        return False
    return stripped.lower() not in _NON_NAME_WORDS


class GreetingMode(BaseModeNode):
    """
    Mode node for first-contact greeting and name collection.

    Responsibilities:
    - Send welcome message on first interaction
    - Extract customer name from the user's response
    - Create customer record in DB via manage_customer tool
    - Transition to GENERAL after name is confirmed
    """

    @property
    def mode_name(self) -> str:
        return "GREETING"

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle the greeting flow.

        Args:
            state: Current conversation state
            intent: IntentResult (not used in GREETING — simple sequential flow)

        Returns:
            Partial state update dict
        """
        conversation_id = state.get("conversation_id", "unknown")
        customer_name = state.get("customer_name")
        is_first = state.get("is_first_interaction", True)
        mode_context = state.get("mode_context") or {}
        greeting_step = mode_context.get("greeting_step")
        suggested_name = mode_context.get("suggested_name")

        self.logger.info(
            "GreetingMode.handle | conversation=%s | customer_name=%s | is_first=%s",
            conversation_id,
            customer_name,
            is_first,
        )

        # ── Anti-loop guard: if name already known, skip to GENERAL ──────────
        if customer_name:
            self.logger.info(
                "GreetingMode: customer_name already set (%s), transitioning to GENERAL",
                customer_name,
            )
            response = _WELCOME_RETURNING.format(name=customer_name)
            return {
                **transition_mode(state, "GENERAL"),
                **add_message(state, "assistant", response),
                "user_message": None,
            }

        # ── Turn 1: first interaction — seed greeting subflow ─────────────────
        if is_first:
            self.logger.info(
                "GreetingMode: first interaction — sending welcome message"
            )
            if suggested_name:
                response = _WELCOME_CONFIRM_SUGGESTED.format(name=suggested_name)
                next_context = {
                    **mode_context,
                    "greeting_step": "confirm_suggested_name",
                    "suggested_name": suggested_name,
                }
            else:
                response = _WELCOME_NEEDS_NAME
                next_context = {**mode_context, "greeting_step": "ask_name"}

            return {
                **add_message(state, "assistant", response),
                "is_first_interaction": False,
                "current_mode": "GREETING",
                "mode_context": next_context,
                "user_message": None,
            }

        # ── Turn 2+: resolve current greeting subflow ─────────────────────────
        user_message = self._get_last_user_message(state)
        intent_name = getattr(intent, "intent", "ambiguous")

        if greeting_step == "confirm_suggested_name" and suggested_name:
            explicit_name = await self._extract_name(user_message)

            if intent_name == "confirm":
                customer_id = await self._create_customer(state, suggested_name)
                response = _CONFIRMATION.format(name=suggested_name)
                return {
                    **transition_mode(state, "GENERAL"),
                    **add_message(state, "assistant", response),
                    "customer_name": suggested_name,
                    "customer_id": customer_id,
                    "user_message": None,
                }

            if explicit_name != "UNKNOWN" and explicit_name != suggested_name:
                customer_id = await self._create_customer(state, explicit_name)
                response = _CONFIRMATION.format(name=explicit_name)
                return {
                    **transition_mode(state, "GENERAL"),
                    **add_message(state, "assistant", response),
                    "customer_name": explicit_name,
                    "customer_id": customer_id,
                    "user_message": None,
                }

            if intent_name == "reject":
                return {
                    **add_message(state, "assistant", _ASK_NAME_AFTER_REJECTION),
                    "current_mode": "GREETING",
                    "mode_context": {
                        **mode_context,
                        "greeting_step": "ask_name",
                    },
                    "user_message": None,
                }

        extracted_name = await self._extract_name(user_message)
        self.logger.info(
            "GreetingMode: extracted_name=%s from user_message=%r",
            extracted_name,
            user_message[:60] if user_message else "",
        )

        if extracted_name and extracted_name != "UNKNOWN":
            # Create customer in DB
            customer_id = await self._create_customer(state, extracted_name)

            response = _CONFIRMATION.format(name=extracted_name)
            return {
                **transition_mode(state, "GENERAL"),
                **add_message(state, "assistant", response),
                "customer_name": extracted_name,
                "customer_id": customer_id,
                "user_message": None,
            }
        else:
            # Could not extract a valid name — ask again
            return {
                **add_message(state, "assistant", _ASK_NAME_AGAIN),
                "current_mode": "GREETING",
                "user_message": None,
            }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_last_user_message(self, state: ConversationState) -> str:
        """Return the content of the most recent user message from history."""
        for msg in reversed(state.get("messages", [])):
            if msg.get("role") == "user":
                return msg.get("content", "")
        # Fallback: check transient user_message field
        return state.get("user_message") or ""

    async def _extract_name(self, user_message: str) -> str:
        """
        Extract a name from the user's message.

        Strategy:
        1. Try heuristic extraction (fast, no LLM)
        2. If heuristic fails, call LLM for NLU-based extraction

        Returns "UNKNOWN" if no valid name can be extracted.
        """
        if not user_message or not user_message.strip():
            return "UNKNOWN"

        # Step 1: Heuristic extraction
        heuristic_result = self._heuristic_extract(user_message)
        if heuristic_result != "UNKNOWN":
            return heuristic_result

        # Step 2: LLM fallback
        try:
            result = await self._call_llm([
                SystemMessage(
                    content=(
                        "Extrae SOLO el nombre del usuario del siguiente mensaje. "
                        "Responde únicamente con el nombre (capitalizado). "
                        "Si no hay un nombre claro, responde exactamente: UNKNOWN"
                    )
                ),
                HumanMessage(content=user_message),
            ])
            if result:
                extracted = (
                    result.content.strip()
                    if hasattr(result, "content")
                    else str(result).strip()
                )
                if extracted and len(extracted) <= 60:
                    # Check sentinel BEFORE title-casing (title() turns "UNKNOWN" → "Unknown"
                    # which would pass _is_valid_name incorrectly)
                    if extracted.upper() == "UNKNOWN":
                        return "UNKNOWN"
                    capitalized = extracted.title()
                    return capitalized if _is_valid_name(capitalized) else "UNKNOWN"
        except Exception as exc:
            self.logger.warning("LLM name extraction failed: %s", exc)

        return "UNKNOWN"

    def _heuristic_extract(self, user_message: str) -> str:
        """
        Extract name via simple heuristic (no LLM).

        Works well for messages like:
        - "Me llamo María" → "María"
        - "Soy Juan Carlos" → "Juan Carlos"
        - "María" → "María"

        Returns "UNKNOWN" if no valid candidate found.
        """
        words = user_message.strip().split()

        # Filter out known filler words
        name_words = [
            cleaned for w in words
            if (cleaned := w.strip(string.punctuation))
            and cleaned.lower() not in _FILLER_WORDS
        ]

        if not name_words:
            return "UNKNOWN"

        # Take the first 1-2 words as the name candidate
        candidate = " ".join(w.capitalize() for w in name_words[:2])
        return candidate if _is_valid_name(candidate) else "UNKNOWN"

    async def _create_customer(
        self, state: ConversationState, name: str
    ) -> str | None:
        """
        Create a new customer record in the database.

        Returns the customer ID string if successful, or None on failure.
        """
        customer_phone = state.get("customer_phone", "")
        if not customer_phone:
            self.logger.warning("GreetingMode: no customer_phone in state — skipping DB creation")
            return None

        try:
            result = await manage_customer.ainvoke({
                "action": "create",
                "phone": customer_phone,
                "data": {"first_name": name},
            })

            if isinstance(result, dict) and "id" in result and "error" not in result:
                customer_id = str(result["id"])
                self.logger.info(
                    "GreetingMode: customer created | id=%s | name=%s | phone=%s",
                    customer_id,
                    name,
                    customer_phone,
                )
                return customer_id
            else:
                self.logger.warning(
                    "GreetingMode: manage_customer returned unexpected result: %s", result
                )
                return None

        except Exception as exc:
            self.logger.error(
                "GreetingMode: customer creation failed | name=%s | error=%s",
                name,
                exc,
            )
            return None
