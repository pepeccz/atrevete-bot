"""
Intent Router - Routes intents to booking or non-booking handlers.

This module implements the routing logic that separates booking flows
(FSM-prescribed tools) from non-booking flows (LLM conversational).

Key decision: Does this intent affect booking progress?
- YES → BookingHandler (prescriptive)
- NO → NonBookingHandler (conversational)

v6.0 Addition: IntentResult dataclass + hybrid keyword+LLM classifier
used by v6.0 mode-based architecture.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent.fsm.models import Intent, IntentType


# ============================================================================
# v6.0 IntentResult — Structured output from the v6.0 intent classifier
# ============================================================================


@dataclass
class IntentResult:
    """
    Structured result from the v6.0 intent classifier.

    Fields:
        intent: One of: greet, book, ask_info, confirm, reject, cancel, escalate, ambiguous
        confidence: Float 0.0-1.0 (1.0 = certain keyword match, <0.8 = LLM inferred)
        raw_input: Original user message (for debugging)
        mode_hint: Suggested mode for router_node (GREETING/BOOKING/GENERAL/ESCALATION),
                   or None for context-dependent intents (confirm/reject/cancel/ambiguous)
    """

    intent: str
    confidence: float = 1.0
    raw_input: str = ""
    mode_hint: str | None = None

    def __post_init__(self) -> None:
        """Clamp confidence to [0.0, 1.0] range."""
        self.confidence = max(0.0, min(1.0, self.confidence))

    def is_booking(self) -> bool:
        """Return True if this intent should route to BOOKING mode."""
        return self.intent == "book"

    def is_greeting(self) -> bool:
        """Return True if this intent should route to GREETING mode."""
        return self.intent == "greet"

    def is_escalation(self) -> bool:
        """Return True if this intent should route to ESCALATION mode."""
        return self.intent == "escalate"

    def is_confirmation(self) -> bool:
        """Return True if user is confirming something."""
        return self.intent == "confirm"

    def is_cancellation(self) -> bool:
        """Return True if user wants to cancel."""
        return self.intent in ("cancel", "reject")


if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

    from agent.fsm import BookingFSM
    from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


# ============================================================================
# v6.0 Keyword classifier — module-level, synchronous, no LLM dependency
# ============================================================================

# Valid intents for the v6.0 classifier
_VALID_INTENTS: frozenset[str] = frozenset({
    "greet", "book", "ask_info", "confirm", "reject",
    "cancel", "escalate", "ambiguous",
})

# Confidence threshold above which the keyword fast-path skips the LLM
_KEYWORD_MATCH_THRESHOLD: float = 0.80

# Keywords per intent — order within each list does not matter.
# Multi-word phrases are supported and matched as substrings.
KEYWORD_MAP: dict[str, list[str]] = {
    "greet": [
        "hola",
        "buenas",
        "buenos días",
        "buenas tardes",
        "buenas noches",
        "hey",
        "saludos",
        "buen día",
    ],
    "book": [
        "cita",
        "reservar",
        "agendar",
        "quiero",
        "turno",
        "pedir hora",
        "coger hora",
        "me gustaría una",
        "solicitar",
        "necesito una",
    ],
    "ask_info": [
        "cuanto cuesta",
        "cuánto cuesta",
        "precio",
        "precios",
        "horario",
        "horarios",
        "servicios",
        "qué hacen",
        "qué ofrecen",
        "información",
        "info",
        "cuánto es",
        "cuanto es",
        "duración",
        "duracion",
    ],
    "confirm": [
        "si",
        "sí",
        "ok",
        "dale",
        "vale",
        "claro",
        "perfecto",
        "correcto",
        "está bien",
        "de acuerdo",
        "confirmo",
        "acepto",
        "exacto",
        "así es",
    ],
    "reject": [
        "mejor no",
        "no quiero",
        "no gracias",
        "nah",
        "para nada",
        "no me interesa",
        "no, gracias",
        "no",
    ],
    "cancel": [
        "cancelar",
        "cancelar cita",
        "cancelar reserva",
        "anular",
        "deshacer",
        "eliminar cita",
        "borrar cita",
    ],
    "escalate": [
        "hablar con una persona",
        "hablar con alguien",
        "hablar con un humano",
        "quiero hablar con",
        "necesito hablar con",
        "agente",
        "encargado",
        "humano",
        "persona real",
        "urgente",
        "reclamar",
        "queja",
    ],
}


def _intent_to_mode_hint(intent: str) -> str | None:
    """
    Map a classified intent to a suggested conversation mode.

    Context-dependent intents (confirm, reject, cancel, ambiguous) return None
    because their correct mode depends on the active conversation context.
    """
    _map: dict[str, str | None] = {
        "greet": "GREETING",
        "book": "BOOKING",
        "ask_info": "GENERAL",
        "escalate": "ESCALATION",
        # context-dependent — router_node uses current_mode to resolve these
        "confirm": None,
        "reject": None,
        "cancel": None,
        "ambiguous": None,
    }
    return _map.get(intent)


def _keyword_matches(text_lower: str, kw_lower: str) -> float:
    """
    Check if a keyword matches the given (already lowercased) text.

    Matching rules:
    - Exact full-text match → 0.90 (highest confidence)
    - Text starts with keyword (at word boundary) → 0.90 (high confidence)
    - Keyword found as whole word anywhere in text → 0.70 (moderate confidence)
    - No match → 0.0

    Word-boundary matching prevents short keywords like "no" from matching
    inside longer words like "unknown" or "información".
    """
    if text_lower == kw_lower:
        return 0.90

    if text_lower.startswith(kw_lower):
        # Ensure it's a word boundary: keyword followed by end-of-string or non-word char
        suffix = text_lower[len(kw_lower):]
        if not suffix or not suffix[0].isalnum():
            return 0.90

    # Whole-word substring match using regex word boundaries
    # \b works with ASCII; for Spanish accents we use a custom boundary check
    pattern = r"(?<![a-záéíóúüñ])" + re.escape(kw_lower) + r"(?![a-záéíóúüñ])"
    if re.search(pattern, text_lower):
        return 0.70

    return 0.0


def classify_by_keywords(text: str) -> IntentResult | None:
    """
    Fast synchronous keyword-based intent classification.

    Returns an IntentResult when a keyword matches with sufficient confidence,
    or None when no keyword matches (triggering the LLM fallback).

    Confidence levels:
    - 0.90: exact full-text match OR text starts with a keyword (word boundary)
    - 0.70: keyword found as a whole word anywhere in the text

    Only confidence >= _KEYWORD_MATCH_THRESHOLD (0.80) bypasses the LLM.
    Substring-only matches (0.70) still trigger LLM for more accurate classification.

    When multiple intents match at the same confidence level, the first match
    (by KEYWORD_MAP insertion order) wins.

    Args:
        text: Raw user message (any case, any leading/trailing whitespace)

    Returns:
        IntentResult or None
    """
    if not text or not text.strip():
        return None

    text_normalized = text.strip().lower()
    best_intent: str | None = None
    best_confidence: float = 0.0

    for intent, keywords in KEYWORD_MAP.items():
        # Find the best-matching keyword for this intent
        intent_best_confidence: float = 0.0
        for kw in keywords:
            kw_lower = kw.lower()
            confidence = _keyword_matches(text_normalized, kw_lower)
            if confidence > intent_best_confidence:
                intent_best_confidence = confidence
                if confidence == 0.90:
                    # Can't do better — short-circuit to next intent
                    break

        # Update global best if this intent scored higher
        if intent_best_confidence > best_confidence:
            best_confidence = intent_best_confidence
            best_intent = intent

    if best_intent is None:
        return None

    return IntentResult(
        intent=best_intent,
        confidence=best_confidence,
        raw_input=text,
        mode_hint=_intent_to_mode_hint(best_intent),
    )


# ============================================================================
# v6.0 IntentRouter — hybrid keyword + LLM classifier
# ============================================================================

# System prompt for the LLM intent classifier (minimal, JSON-only)
_LLM_SYSTEM_PROMPT = """\
Eres un clasificador de intenciones para un asistente de reservas de peluquería.
Clasifica el mensaje del usuario en UNA de estas intenciones:
greet, book, ask_info, confirm, reject, cancel, escalate, ambiguous

Responde ÚNICAMENTE con JSON válido, sin comentarios ni texto extra:
{"intent": "<intención>", "confidence": <0.0-1.0>}

Intenciones:
- greet: saludo, presentación
- book: quiere hacer o gestionar una reserva/cita
- ask_info: pregunta sobre precios, servicios, horarios, información general
- confirm: confirma algo propuesto
- reject: rechaza algo propuesto
- cancel: quiere cancelar una cita existente
- escalate: quiere hablar con una persona real
- ambiguous: no queda claro"""


class IntentRouter:
    """
    Routes intents to appropriate handler based on intent type.

    v5.0 API: @staticmethod route() — routes to BookingHandler or NonBookingHandler
    v6.0 API: __init__(llm_client) + async classify() — hybrid keyword+LLM classifier

    Both APIs coexist for backward compatibility.
    """

    # ---- v5.0 constants (backward compatibility) ----

    # Intents that affect booking flow state
    BOOKING_INTENTS = {
        IntentType.START_BOOKING,
        IntentType.SELECT_SERVICE,
        IntentType.CONFIRM_SERVICES,
        IntentType.SELECT_STYLIST,
        IntentType.CHECK_AVAILABILITY,  # Part of booking flow
        IntentType.SELECT_SLOT,
        IntentType.PROVIDE_CUSTOMER_DATA,
        IntentType.CONFIRM_BOOKING,
        IntentType.CANCEL_BOOKING,
    }

    # Intents that don't affect booking state
    NON_BOOKING_INTENTS = {
        IntentType.GREETING,
        IntentType.FAQ,
        IntentType.ESCALATE,
        IntentType.UNKNOWN,
        IntentType.UPDATE_NAME,  # Name update in IDLE state
        # Appointment confirmation intents (48h confirmation flow)
        IntentType.CONFIRM_APPOINTMENT,
        IntentType.DECLINE_APPOINTMENT,
        # Double confirmation intents (decline flow) - v3.5
        IntentType.CONFIRM_DECLINE,
        IntentType.ABORT_DECLINE,
    }

    # ---- v6.0 instance API ----

    def __init__(self, llm_client: Any) -> None:
        """
        Initialize the v6.0 hybrid classifier.

        Args:
            llm_client: A LangChain-compatible LLM client with an `ainvoke` method.
                        Typically a ChatOpenAI instance pointing at OpenRouter.
        """
        self._llm = llm_client
        logger.debug("IntentRouter v6.0 initialized")

    async def classify(
        self,
        text: str,
        current_mode: str | None = None,
    ) -> IntentResult:
        """
        Classify user message intent using keyword fast-path or LLM fallback.

        Algorithm:
        1. Empty/whitespace → return ambiguous immediately (no LLM call)
        2. classify_by_keywords() → confidence >= _KEYWORD_MATCH_THRESHOLD → return (no LLM call)
        3. LLM fallback with system + human prompt (includes current_mode for context)
        4. Parse LLM response: strip markdown fences, parse JSON, validate intent
        5. Any failure (invalid JSON, unknown intent, exception) → return ambiguous(0.0)

        Args:
            text: Raw user message
            current_mode: Active conversation mode (GREETING/BOOKING/GENERAL/ESCALATION),
                          passed to the LLM for context-dependent classification

        Returns:
            IntentResult — never raises
        """
        # Step 1: Empty input fast-path
        if not text or not text.strip():
            return IntentResult(
                intent="ambiguous",
                confidence=0.0,
                raw_input=text or "",
                mode_hint=None,
            )

        # Step 2: Keyword fast-path
        keyword_result = classify_by_keywords(text)
        if keyword_result is not None and keyword_result.confidence >= _KEYWORD_MATCH_THRESHOLD:
            logger.debug(
                "IntentRouter: keyword fast-path | intent=%s | confidence=%.2f",
                keyword_result.intent,
                keyword_result.confidence,
            )
            return keyword_result

        # Step 3: LLM fallback
        logger.debug(
            "IntentRouter: LLM fallback | keyword_result=%s | text_preview=%s",
            keyword_result.intent if keyword_result else "None",
            text[:60],
        )
        return await self._classify_with_llm(text, current_mode)

    async def _classify_with_llm(
        self,
        text: str,
        current_mode: str | None,
    ) -> IntentResult:
        """
        Call the LLM to classify intent when keywords are insufficient.

        Handles: invalid JSON, markdown fences, unknown intents, network errors.
        On any failure returns IntentResult(intent="ambiguous", confidence=0.0).
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        mode_context = f"\nModo actual de la conversación: {current_mode}" if current_mode else ""
        human_content = f"Mensaje: {text}{mode_context}"

        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=_LLM_SYSTEM_PROMPT),
                HumanMessage(content=human_content),
            ])
            raw_content: str = response.content

            # Strip markdown fences if present (```json ... ```)
            cleaned = raw_content.strip()
            fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
            if fence_match:
                cleaned = fence_match.group(1).strip()

            data: dict[str, Any] = json.loads(cleaned)
            intent_value: str = str(data.get("intent", "ambiguous")).lower()
            confidence_value: float = float(data.get("confidence", 0.5))

            # Reject unknown intents
            if intent_value not in _VALID_INTENTS:
                logger.warning(
                    "IntentRouter LLM returned unknown intent=%s, mapping to ambiguous",
                    intent_value,
                )
                intent_value = "ambiguous"
                confidence_value = 0.0

            return IntentResult(
                intent=intent_value,
                confidence=confidence_value,
                raw_input=text,
                mode_hint=_intent_to_mode_hint(intent_value),
            )

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.warning("IntentRouter LLM response parse error: %s", exc)
        except Exception as exc:
            logger.error("IntentRouter LLM call failed: %s", exc)

        return IntentResult(
            intent="ambiguous",
            confidence=0.0,
            raw_input=text,
            mode_hint=None,
        )

    # ---- v5.0 static method (backward compatibility) ----

    @staticmethod
    async def route(
        intent: Intent,
        fsm: "BookingFSM",
        state: "ConversationState",
        llm: "ChatOpenAI",
    ) -> tuple[str, dict | None]:
        """
        Route intent to appropriate handler.

        Args:
            intent: Extracted user intent
            fsm: BookingFSM instance (contains state + collected_data)
            state: Conversation state
            llm: LLM client for response generation

        Returns:
            Tuple of (response_text, state_updates)
            - response_text: Assistant response text
            - state_updates: Dict of state fields to update (or None)
        """
        is_booking = intent.type in IntentRouter.BOOKING_INTENTS

        logger.info(
            f"Routing intent | type={intent.type.value} | "
            f"is_booking={is_booking} | fsm_state={fsm.state.value}"
        )

        if is_booking:
            # Prescriptive flow: FSM decides tools
            from agent.routing.booking_handler import BookingHandler

            handler = BookingHandler(fsm, state, llm)
            return await handler.handle(intent), None
        else:
            # Conversational flow: LLM handles with safe tools
            from agent.routing.non_booking_handler import NonBookingHandler

            handler = NonBookingHandler(state, llm, fsm)
            # NonBookingHandler returns (response, state_updates)
            return await handler.handle(intent)
