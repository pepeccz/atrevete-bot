"""
Intent Router — v6.0 keyword-only intent classifier.

Produces an IntentResult (intent, confidence, raw_input, mode_hint) consumed
by ``router_node`` in ``agent/graphs/conversation_flow.py`` to drive the
mode-based conversation graph.

Design: when keywords do not match above ``_KEYWORD_MATCH_THRESHOLD`` the
classifier returns ``intent="ambiguous"`` — resolution is deferred to the mode
node's own LLM call (single-LLM-per-turn architecture). There is no separate
LLM invocation at the routing layer.
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

    from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)


# ============================================================================
# v6.0 Keyword classifier — module-level, synchronous, no LLM dependency
# ============================================================================

# Valid intents for the v6.0 classifier
_VALID_INTENTS: frozenset[str] = frozenset(
    {
        "greet",
        "book",
        "ask_info",
        "confirm",
        "reject",
        "cancel",
        "escalate",
        "retry",
        "reschedule",
        "check_appointments",
        "ambiguous",
    }
)

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
        "como estas",
        "wenas",
        "qué tal",  # "qué tal" can match mid-conversation, monitor
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
        # Servicios coloquiales (peluquería)
        "corte",
        "cortar",
        "cortarme",
        "cortarme el pelo",
        "corte de pelo",
        "pelo",
        "peluquería",
        "peluqueria",
        "peinado",
        "peinar",
        "peinarme",
        "color",
        "tinte",
        "teñir",
        "teñirme",
        "mechas",
        # Servicios coloquiales (estética)
        "uñas",
        "unas",
        "manicura",
        "pedicura",
        "hacerme las uñas",
        "depilación",
        "depilacion",
        "depilarme",
        "cejas",
        "diseño de cejas",
        "masaje",
        "tratamiento",
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
        "dlae",
        "dlee",
        "dales",
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
        "va",
        "listo",
        "hecho",
        "venga ya",
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
        "nel",
        "nop",
        "qué va",
        "ni hablar",
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
        "reclamación",
        "quiero quejarme",
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
    "reschedule": [
        "reagendar",
        "reagendá",
        "reagendarme",
        "reagendame",
        "cambiar cita",
        "cambiar mi cita",
        "cambiar turno",
        "cambiar mi turno",
        "mover cita",
        "mover mi cita",
        "mover turno",
        "mover mi turno",
        "reprogramar",
        "reprogramá",
        "reprogramarme",
        "cambiar la fecha",
        "cambiar el día",
        "cambiar el horario",
        "otro día",
        "otro horario",
        "otra fecha",
        "postergar",
        "adelantar la cita",
    ],
    "check_appointments": [
        "mi cita",
        "mis citas",
        "mi turno",
        "mis turnos",
        "cuándo tengo",
        "cuando tengo",
        "cuándo es mi cita",
        "cuando es mi cita",
        "próxima cita",
        "proxima cita",
        "próximo turno",
        "proximo turno",
        "ver mis citas",
        "ver mis turnos",
        "tengo turno",
        "tengo cita",
        "qué citas tengo",
        "que citas tengo",
        "recordarme",
        "recordatorio",
    ],
}


# ============================================================================
# Explicit handoff phrases — used by router override (T2.1 / T2.2)
# ============================================================================

EXPLICIT_HANDOFF_PHRASES: frozenset[str] = frozenset(
    {
        "hablar con alguien",
        "hablar con una persona",
        "hablar con un humano",
        "persona real",
        "quiero hablar con",
        "no quiero hablar con un bot",
        "necesito hablar con alguien",
    }
)


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
        "reschedule": "APPOINTMENT_MANAGEMENT",
        "check_appointments": "APPOINTMENT_MANAGEMENT",
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
        suffix = text_lower[len(kw_lower) :]
        if not suffix or not suffix[0].isalnum():
            return 0.90

    # Whole-word substring match using regex word boundaries
    # \b works with ASCII; for Spanish accents we use a custom boundary check
    pattern = r"(?<![a-záéíóúüñ])" + re.escape(kw_lower) + r"(?![a-záéíóúüñ])"
    if re.search(pattern, text_lower):
        return 0.70

    return 0.0


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

    # APPOINTMENT_MANAGEMENT bare-digit shortcut: "1", "2 martes", etc. → confirm
    # so the appointment management flow handles selection instead of misrouting.
    if (
        _ctx.get("current_mode") == "APPOINTMENT_MANAGEMENT"
        and re.match(r"^\d+(\s+\w+)?$", text_normalized)
    ):
        logger.debug(
            "classify_by_keywords: APPOINTMENT_MANAGEMENT bare-digit shortcut | text=%r → confirm(0.95)",
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
    best_kw_len: int = 0  # length of best-matching keyword (longer = more specific)

    # Collect ALL intents that match above threshold to detect conflicts
    matched_intents: dict[str, float] = {}

    for intent, keywords in KEYWORD_MAP.items():
        # Find the best-matching keyword for this intent
        intent_best_confidence: float = 0.0
        intent_best_kw_len: int = 0
        for kw in keywords:
            kw_lower = kw.lower()
            confidence = _keyword_matches(text_normalized, kw_lower)
            if confidence > intent_best_confidence or (
                confidence == intent_best_confidence and len(kw_lower) > intent_best_kw_len
            ):
                intent_best_confidence = confidence
                intent_best_kw_len = len(kw_lower)
                if confidence == 0.90 and len(kw_lower) >= len(text_normalized):
                    # Exact full-text match — can't do better — short-circuit
                    break

        if intent_best_confidence > 0.0:
            matched_intents[intent] = intent_best_confidence

        # Update global best: prefer higher confidence, then longer keyword on ties
        if intent_best_confidence > best_confidence or (
            intent_best_confidence == best_confidence
            and intent_best_confidence > 0.0
            and intent_best_kw_len > best_kw_len
        ):
            best_confidence = intent_best_confidence
            best_intent = intent
            best_kw_len = intent_best_kw_len

    if best_intent is None:
        return None

    # Multi-intent conflict detection:
    # When a greeting co-occurs with an actionable intent (book, ask_info,
    # cancel, escalate), defer to LLM for accurate classification.
    _ACTIONABLE_INTENTS = {"book", "ask_info", "cancel", "escalate"}
    if best_intent == "greet" and any(i in matched_intents for i in _ACTIONABLE_INTENTS):
        logger.debug(
            "classify_by_keywords: multi-intent conflict detected (greet + %s) — deferring to LLM",
            [i for i in _ACTIONABLE_INTENTS if i in matched_intents],
        )
        return None

    # Greet passthrough: ALWAYS defer greet to LLM — the LLM correctly handles
    # compound greetings with typos that keywords can't detect.
    if best_intent == "greet":
        logger.debug(
            "classify_by_keywords: greet passthrough — deferring to LLM | text_preview=%s",
            text[:60],
        )
        return None

    return IntentResult(
        intent=best_intent,
        confidence=best_confidence,
        raw_input=text,
        mode_hint=_intent_to_mode_hint(best_intent),
    )


# ============================================================================
# v6.0 IntentRouter — keyword-only classifier
# ============================================================================


class IntentRouter:
    """
    v6.0 keyword-only intent classifier.

    If ``classify_by_keywords`` finds a match with confidence >=
    ``_KEYWORD_MATCH_THRESHOLD`` the router returns that result; otherwise it
    returns ``intent="ambiguous"`` and the mode node's own LLM resolves the
    turn (single-LLM-per-turn architecture).
    """

    def __init__(self) -> None:
        logger.debug("IntentRouter v6.0 initialized (keyword-only)")

    async def classify(
        self,
        text: str,
        current_mode: str | None = None,
        booking_step: str | None = None,
    ) -> IntentResult:
        """
        Classify user message intent using the keyword fast-path only.

        Algorithm:
        1. Empty/whitespace → return ambiguous
        2. classify_by_keywords() with confidence >= _KEYWORD_MATCH_THRESHOLD → return it
        3. Otherwise → return ambiguous (mode node will resolve via its LLM)

        Args:
            text: Raw user message
            current_mode: Active conversation mode, passed to the keyword classifier
                          for context-dependent shortcuts (e.g. BOOKING slot selection)
            booking_step: Current booking sub-step (e.g. "slot_selection")

        Returns:
            IntentResult — never raises, never calls an LLM
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

        # Step 3: Defer to mode node — no separate LLM call here
        keyword_confidence = keyword_result.confidence if keyword_result is not None else 0.0
        logger.debug(
            "IntentRouter: deferring to mode node | keyword_intent=%s | kw_conf=%.2f | text_preview=%s",
            keyword_result.intent if keyword_result else "None",
            keyword_confidence,
            text[:60],
        )
        return IntentResult(
            intent="ambiguous",
            confidence=keyword_confidence,
            raw_input=text,
            mode_hint=None,
        )
