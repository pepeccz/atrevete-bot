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
        intent: One of: greet, book, ask_info, confirm, reject, cancel, escalate, retry, ambiguous
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

    def is_retry(self) -> bool:
        """Return True if user wants to retry a failed action."""
        return self.intent == "retry"


if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

    from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


# ============================================================================
# v6.0 Keyword classifier — module-level, synchronous, no LLM dependency
# ============================================================================

# Valid intents for the v6.0 classifier
_VALID_INTENTS: frozenset[str] = frozenset({
    "greet", "book", "ask_info", "confirm", "reject",
    "cancel", "escalate", "retry", "ambiguous",
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
        "no",
        "mejor no",
        "no quiero",
        "no gracias",
        "nah",
        "para nada",
        "no me interesa",
        "no, gracias",
    ],
    "cancel": [
        "cancelar",
        "cancelar cita",
        "cancelar reserva",
        "anular",
        "deshacer",
        "eliminar cita",
        "borrar cita",
        "cancelo",
        "cancela",
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
    "retry": [
        "intentar",
        "intentalo",
        "otra vez",
        "de nuevo",
        "reintentar",
        "vuelve a intentar",
        "intenta de nuevo",
        "intentalo de nuevo",
        "volver a intentar",
        "probemos de nuevo",
        "una vez mas",
        "repetir",
    ],
}


# ============================================================================
# Explicit handoff phrases — used by router override (T2.1 / T2.2)
# ============================================================================

EXPLICIT_HANDOFF_PHRASES: frozenset[str] = frozenset({
    "hablar con alguien",
    "hablar con una persona",
    "hablar con un humano",
    "persona real",
    "quiero hablar con",
    "no quiero hablar con un bot",
    "necesito hablar con alguien",
})


def _is_explicit_handoff(text: str) -> bool:
    """
    Return True if the message contains an explicit human-handoff phrase.

    This helper is intentionally narrow — it only matches phrases that
    unambiguously mean the user wants a human agent.  Short/ambiguous phrases
    like "quiero hablar" do NOT match so that the LLM retains control of
    borderline cases.

    Args:
        text: Raw user message (any case)

    Returns:
        True if any phrase in EXPLICIT_HANDOFF_PHRASES is a substring
        of the lowercased message.
    """
    if not text:
        return False
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in EXPLICIT_HANDOFF_PHRASES)


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
        "retry": None,
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


_BOOKING_NO_PREF_PHRASES: tuple[str, ...] = (
    "no tengo preferencia",
    "sin preferencia",
    "cualquiera",
    "no importa",
    "nada mas",
    "nada más",
    "no, nada",
)

_EXPLICIT_CANCEL_PHRASES: tuple[str, ...] = (
    "quiero cancelar",
    "cancelar mi cita",
    "cancelar la cita",
    "cancelar reserva",
    "anular",
)


def classify_by_keywords(text: str, context: dict | None = None) -> IntentResult | None:
    """
    Fast synchronous keyword-based intent classification.

    Returns an IntentResult when a keyword matches with sufficient confidence,
    or None when no keyword matches (triggering the LLM fallback).

    Confidence levels:
    - 0.90: exact full-text match OR text starts with a keyword (word boundary)
    - 0.70: keyword found as a whole word anywhere in the text

    Only confidence >= _KEYWORD_MATCH_THRESHOLD (0.80) bypasses the LLM.
    Substring-only matches (0.70) still trigger LLM for more accurate classification.

    Multi-intent conflict resolution:
    - When both a social intent (greet) and an actionable intent (book, ask_info,
      cancel, escalate) match above threshold, return None to defer to the LLM.
      This prevents "Hola, quiero cortarme el pelo" from being classified as
      just "greet" — the LLM correctly identifies the dominant intent.

    When multiple intents match at the same confidence level, the first match
    (by KEYWORD_MAP insertion order) wins.

    Booking-context narrowing (context["current_mode"] == "BOOKING"):
    - No-preference and qualifier phrases downgrade `reject` confidence to ≤0.40
      so they fall through to the LLM / substep handler instead of triggering
      an early-exit cancel. Explicit cancel phrases are unaffected.

    Slot-selection shortcut (context["booking_step"] == "slot_selection"):
    - A bare digit reply ("1", "2", "3", ...) is classified as "confirm" with
      confidence 0.95 so it reaches _handle_slot_selection instead of
      triggering the cancel/reject early-exit path.

    Args:
        text: Raw user message (any case, any leading/trailing whitespace)
        context: Optional runtime context dict, e.g.
            {"current_mode": "BOOKING", "booking_step": "slot_selection"}

    Returns:
        IntentResult or None
    """
    if not text or not text.strip():
        return None

    text_normalized = text.strip().lower()

    # Slot-selection shortcut: bare digit → "confirm" so the FSM slot resolver
    # can handle it instead of the reject/cancel early-exit path.
    _ctx = context or {}
    if (
        _ctx.get("current_mode") == "BOOKING"
        and _ctx.get("booking_step") == "slot_selection"
        and re.match(r"^\d+$", text_normalized)
    ):
        logger.debug(
            "classify_by_keywords: slot_selection bare-digit shortcut | text=%r → confirm(0.95)",
            text,
        )
        return IntentResult(
            intent="confirm",
            confidence=0.95,
            raw_input=text,
            mode_hint=None,
        )
    best_intent: str | None = None
    best_confidence: float = 0.0

    # Collect ALL intents that match above threshold to detect conflicts
    matched_intents: dict[str, float] = {}

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

        if intent_best_confidence > 0.0:
            matched_intents[intent] = intent_best_confidence

        # Update global best if this intent scored higher
        if intent_best_confidence > best_confidence:
            best_confidence = intent_best_confidence
            best_intent = intent

    if best_intent is None:
        return None

    # Multi-intent conflict detection:
    # When a greeting co-occurs with an actionable intent (book, ask_info,
    # cancel, escalate), defer to LLM for accurate classification.
    _ACTIONABLE_INTENTS = {"book", "ask_info", "cancel", "escalate"}
    if best_intent == "greet" and any(
        i in matched_intents for i in _ACTIONABLE_INTENTS
    ):
        logger.debug(
            "classify_by_keywords: multi-intent conflict detected "
            "(greet + %s) — deferring to LLM",
            [i for i in _ACTIONABLE_INTENTS if i in matched_intents],
        )
        return None

    # Booking-context narrowing: downgrade `reject` for no-preference / qualifier
    # phrases so they fall through to the LLM rather than triggering an early exit.
    if (
        best_intent == "reject"
        and (context or {}).get("current_mode") == "BOOKING"
    ):
        # Explicit cancel phrases must keep full confidence regardless
        is_explicit_cancel = any(phrase in text_normalized for phrase in _EXPLICIT_CANCEL_PHRASES)
        if not is_explicit_cancel:
            is_no_pref = any(phrase in text_normalized for phrase in _BOOKING_NO_PREF_PHRASES)
            if is_no_pref:
                logger.debug(
                    "classify_by_keywords: BOOKING context no-preference downgrade "
                    "| text_preview=%s",
                    text[:60],
                )
                best_confidence = min(best_confidence, 0.40)

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
greet, book, ask_info, confirm, reject, cancel, escalate, retry, ambiguous

Responde ÚNICAMENTE con JSON válido, sin comentarios ni texto extra:
{"intent": "<intención>", "confidence": <0.0-1.0>}

Intenciones:
- greet: saludo puro sin otra intención (ej: "Hola", "Buenas tardes")
- book: quiere hacer o gestionar una reserva/cita
- ask_info: pregunta sobre precios, servicios, horarios, información general
- confirm: confirma algo propuesto
- reject: rechaza algo propuesto
- cancel: quiere cancelar una cita existente
- escalate: quiere hablar con una persona real
- retry: quiere volver a intentar algo que falló (ej: "intentalo de nuevo", "otra vez", "probemos de nuevo")
- ambiguous: no queda claro

REGLA IMPORTANTE: Si el mensaje contiene un saludo ("hola", "buenas") JUNTO \
con una intención de acción (reservar, preguntar, cancelar), clasifica según \
la ACCIÓN, NO como greet. Ejemplo: "Hola, quiero cortarme el pelo" → book.

REGLA DE CONTEXTO: Si el current_mode es BOOKING, las preguntas sobre \
estilistas, disponibilidad, horarios o el servicio seleccionado son parte \
de la reserva. Clasifica como "book", NO como "ask_info"."""


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
        booking_step: str | None = None,
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
            booking_step: Current booking sub-step (e.g. "slot_selection"), used to
                          classify bare digit replies as "confirm" at the right substep

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

        # Step 2: Keyword fast-path (pass current_mode + booking_step for context narrowing)
        kw_context: dict | None = None
        if current_mode or booking_step:
            kw_context = {}
            if current_mode:
                kw_context["current_mode"] = current_mode
            if booking_step:
                kw_context["booking_step"] = booking_step
        keyword_result = classify_by_keywords(text, kw_context)
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
