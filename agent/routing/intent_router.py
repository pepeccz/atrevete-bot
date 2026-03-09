"""
Intent Router - Keyword + LLM hybrid intent classification.

This module implements the new mode-based intent routing for v6.0 architecture.
It replaces the FSM-driven IntentRouter with a lightweight classifier that:

1. First tries keyword matching (fast, no LLM cost)
2. Falls back to LLM classification only when keywords are ambiguous

The `IntentRouter` class is the main entry point. Use `classify_by_keywords()`
for fast synchronous keyword matching, or `IntentRouter.classify()` for the
full hybrid flow.

Architecture (v6.0):
    User message
        ↓
    classify_by_keywords() — confidence >= 0.8 → return immediately
        ↓ (only if confidence < 0.8)
    LLM classify() — minimal prompt, structured JSON output
        ↓
    IntentResult(intent, confidence, raw_input, mode_hint)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


# ============================================================================
# Intent Type
# ============================================================================

IntentType = Literal[
    "greet",
    "book",
    "ask_info",
    "confirm",
    "reject",
    "cancel",
    "escalate",
    "ambiguous",
]
"""
Simplified intent types for the mode-based architecture (v6.0).

Maps to conversation modes:
- greet     → GREETING mode
- book      → BOOKING mode
- ask_info  → GENERAL mode
- confirm   → context-dependent (continue in current mode)
- reject    → context-dependent (go back / change choice)
- cancel    → BOOKING mode (cancel flow)
- escalate  → ESCALATION mode
- ambiguous → stay in current mode, ask for clarification
"""


# ============================================================================
# Keyword Map
# ============================================================================

KEYWORD_MAP: dict[str, list[str]] = {
    "greet": [
        "hola",
        "buenas",
        "hey",
        "hi",
        "buen dia",
        "buenas tardes",
        "buenas noches",
        "buenos dias",
        "buen día",
        "buenos días",
        "saludos",
    ],
    "book": [
        "cita",
        "reserva",
        "turno",
        "agendar",
        "quiero",
        "necesito",
        "me gustaria",
        "me gustaría",
        "disponibilidad",
        "cuando",
        "cuándo",
        "hora",
        "reservar",
        "apuntarme",
        "pedir cita",
    ],
    "ask_info": [
        "precio",
        "costo",
        "cuanto",
        "cuánto",
        "servicio",
        "que hacen",
        "qué hacen",
        "información",
        "informacion",
        "info",
        "horario",
        "direccion",
        "dirección",
        "donde",
        "dónde",
        "catalogo",
        "catálogo",
        "tratamiento",
    ],
    "confirm": [
        "si",
        "sí",
        "dale",
        "ok",
        "bueno",
        "confirmo",
        "perfecto",
        "genial",
        "claro",
        "correcto",
        "adelante",
        "confirmar",
        "exacto",
        "afirmativo",
    ],
    "reject": [
        "no",
        "nope",
        "cancel",
        "no quiero",
        "cambiar",
        "otro",
        "diferente",
        "mejor no",
        "dejalo",
        "déjalo",
        "cambio",
    ],
    "cancel": [
        "cancelar",
        "anular",
        "borrar",
        "eliminar mi cita",
        "no voy a poder",
        "no puedo ir",
        "quiero cancelar",
    ],
    "escalate": [
        "humano",
        "persona",
        "hablar con",
        "asesor",
        "ayuda",
        "urgente",
        "problema",
        "manager",
        "jefe",
        "encargado",
        "queja",
        "reclamacion",
        "reclamación",
    ],
}


# ============================================================================
# IntentResult
# ============================================================================


@dataclass
class IntentResult:
    """
    Result of intent classification.

    Attributes:
        intent: Classified intent type (one of IntentType literals).
        confidence: Float in [0.0, 1.0] — how certain the classifier is.
        raw_input: Original user message text.
        mode_hint: Optional suggested mode to transition to (may be None if
                   intent doesn't clearly imply a mode change).
    """

    intent: str  # IntentType literal
    confidence: float
    raw_input: str
    mode_hint: str | None = None

    def __post_init__(self) -> None:
        # Clamp confidence to valid range
        self.confidence = max(0.0, min(1.0, self.confidence))


# ============================================================================
# Keyword classifier
# ============================================================================

# Keyword confidence when matched
_KEYWORD_HIGH_CONFIDENCE: float = 0.90
_KEYWORD_LOW_CONFIDENCE: float = 0.70
_KEYWORD_MATCH_THRESHOLD: float = 0.80  # Minimum to skip LLM fallback


def classify_by_keywords(text: str) -> "IntentResult | None":
    """
    Fast keyword-based intent classification (synchronous, no LLM).

    Checks the input text (lowercased) against KEYWORD_MAP for each intent.
    Returns an IntentResult if a keyword matches, else None.

    Confidence levels:
    - Exact match on the first word → 0.90 (high)
    - Partial match anywhere in text → 0.70 (medium, below LLM fallback threshold)

    Args:
        text: Raw user message to classify.

    Returns:
        IntentResult if a keyword matches, None if no match found.

    Examples:
        >>> classify_by_keywords("hola")
        IntentResult(intent='greet', confidence=0.90, ...)
        >>> classify_by_keywords("quiero una cita")
        IntentResult(intent='book', confidence=0.90, ...)
        >>> classify_by_keywords("xyz unknown text")
        None
    """
    if not text or not text.strip():
        return None

    text_lower = text.lower().strip()
    words = text_lower.split()

    best_intent: str | None = None
    best_confidence: float = 0.0

    for intent_name, keywords in KEYWORD_MAP.items():
        for keyword in keywords:
            keyword_lower = keyword.lower()

            # Exact full-text match (e.g., "hola" == "hola")
            if text_lower == keyword_lower:
                if _KEYWORD_HIGH_CONFIDENCE > best_confidence:
                    best_confidence = _KEYWORD_HIGH_CONFIDENCE
                    best_intent = intent_name
                break  # No need to check other keywords for this intent

            # Match if text STARTS with keyword (e.g., "hola como estas" starts with "hola")
            if text_lower.startswith(keyword_lower + " ") or text_lower.startswith(keyword_lower + ","):
                if _KEYWORD_HIGH_CONFIDENCE > best_confidence:
                    best_confidence = _KEYWORD_HIGH_CONFIDENCE
                    best_intent = intent_name
                break

            # Word-level match for multi-word keywords (e.g., "no voy a poder")
            if " " in keyword_lower and keyword_lower in text_lower:
                if _KEYWORD_HIGH_CONFIDENCE > best_confidence:
                    best_confidence = _KEYWORD_HIGH_CONFIDENCE
                    best_intent = intent_name
                break

            # Single-word keyword appears anywhere in text
            if keyword_lower in words:
                if _KEYWORD_LOW_CONFIDENCE > best_confidence:
                    best_confidence = _KEYWORD_LOW_CONFIDENCE
                    best_intent = intent_name
                # Don't break — a better (higher confidence) intent may match

    if best_intent is None:
        return None

    mode_hint = _intent_to_mode_hint(best_intent)

    logger.debug(
        "Keyword classification | intent=%s | confidence=%.2f | text=%s",
        best_intent,
        best_confidence,
        text[:50],
    )

    return IntentResult(
        intent=best_intent,
        confidence=best_confidence,
        raw_input=text,
        mode_hint=mode_hint,
    )


def _intent_to_mode_hint(intent: str) -> str | None:
    """Map intent to a suggested ConversationMode (or None if ambiguous)."""
    mapping: dict[str, str | None] = {
        "greet": "GREETING",
        "book": "BOOKING",
        "ask_info": "GENERAL",
        "confirm": None,      # Depends on current mode
        "reject": None,       # Depends on current mode
        "cancel": "BOOKING",  # Cancel booking flow
        "escalate": "ESCALATION",
        "ambiguous": None,
    }
    return mapping.get(intent)


# ============================================================================
# IntentRouter — hybrid keyword + LLM classifier
# ============================================================================

# Prompt template for LLM fallback classification
_LLM_CLASSIFY_SYSTEM = (
    "Eres un clasificador de intenciones para un bot de WhatsApp de una peluquería. "
    "Clasifica el mensaje en UNA de estas categorías: "
    "greet, book, ask_info, confirm, reject, cancel, escalate, ambiguous. "
    "Responde SOLO en JSON: {\"intent\": \"...\", \"confidence\": 0.0-1.0}"
)

_LLM_CLASSIFY_HUMAN_TEMPLATE = (
    "Contexto actual: {current_mode}\n"
    "Mensaje: \"{message}\"\n"
    "\n"
    "Clasifica el mensaje. JSON solo:"
)


class IntentRouter:
    """
    Keyword + LLM hybrid intent router for v6.0 mode-based architecture.

    Two-stage classification:
    1. Fast keyword matching — if confidence >= 0.8, return immediately (no LLM)
    2. LLM fallback — minimal prompt, structured JSON output

    Thread-safety: stateless (no shared mutable state). Safe to share across
    concurrent coroutines.

    Usage:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="...", ...)
        router = IntentRouter(llm_client=llm)
        result = await router.classify("Quiero una cita", current_mode="GREETING")
    """

    def __init__(self, llm_client: Any) -> None:
        """
        Initialise the IntentRouter.

        Args:
            llm_client: LLM client for fallback classification. Must support
                        ``ainvoke(messages)`` and return an object with ``.content``.
                        Typically a ``langchain_openai.ChatOpenAI`` instance.
        """
        self._llm = llm_client

    async def classify(
        self,
        text: str,
        current_mode: str | None = None,
    ) -> IntentResult:
        """
        Classify user message intent using keyword matching + optional LLM fallback.

        Flow:
        1. Run keyword matching synchronously.
        2. If keyword confidence >= 0.8 → return immediately (no LLM call).
        3. Otherwise → call LLM with minimal prompt.
        4. Parse LLM JSON response into IntentResult.
        5. On any error → return ambiguous with confidence=0.0.

        Args:
            text: Raw user message text.
            current_mode: Current ConversationMode (for context in LLM prompt).
                          Pass None if unknown or at conversation start.

        Returns:
            IntentResult with classified intent, confidence, and optional mode_hint.
        """
        if not text or not text.strip():
            logger.debug("classify: empty text → ambiguous")
            return IntentResult(
                intent="ambiguous",
                confidence=0.0,
                raw_input=text or "",
                mode_hint=None,
            )

        # Stage 1: keyword matching
        keyword_result = classify_by_keywords(text)

        if keyword_result is not None and keyword_result.confidence >= _KEYWORD_MATCH_THRESHOLD:
            logger.info(
                "IntentRouter: keyword match (skipping LLM) | intent=%s | confidence=%.2f | text=%s",
                keyword_result.intent,
                keyword_result.confidence,
                text[:50],
            )
            return keyword_result

        # Stage 2: LLM fallback
        logger.info(
            "IntentRouter: keyword confidence %.2f < %.2f — calling LLM | text=%s",
            keyword_result.confidence if keyword_result else 0.0,
            _KEYWORD_MATCH_THRESHOLD,
            text[:50],
        )
        return await self._classify_with_llm(text, current_mode, keyword_result)

    async def _classify_with_llm(
        self,
        text: str,
        current_mode: str | None,
        keyword_hint: "IntentResult | None",
    ) -> IntentResult:
        """
        LLM-based fallback classification.

        Builds a minimal prompt and parses the JSON response. On any error
        (parse failure, network, etc.), returns ambiguous with confidence=0.0.

        Args:
            text: Raw user message.
            current_mode: Current mode for LLM context.
            keyword_hint: Optional keyword result to log (not passed to LLM).

        Returns:
            IntentResult from LLM classification, or ambiguous on failure.
        """
        try:
            mode_context = current_mode or "desconocido"
            human_text = _LLM_CLASSIFY_HUMAN_TEMPLATE.format(
                current_mode=mode_context,
                message=text,
            )

            messages = [
                SystemMessage(content=_LLM_CLASSIFY_SYSTEM),
                HumanMessage(content=human_text),
            ]

            response = await self._llm.ainvoke(messages)
            response_text = response.content if hasattr(response, "content") else str(response)

            return self._parse_llm_response(text, response_text)

        except Exception as exc:
            logger.warning(
                "IntentRouter: LLM classification failed — returning ambiguous | "
                "error=%s | text=%s",
                exc,
                text[:50],
            )
            return IntentResult(
                intent="ambiguous",
                confidence=0.0,
                raw_input=text,
                mode_hint=None,
            )

    def _parse_llm_response(self, raw_input: str, response_text: str) -> IntentResult:
        """
        Parse LLM JSON response into an IntentResult.

        Handles markdown code fences (```json ... ```) and malformed JSON
        gracefully by returning ambiguous with confidence=0.0.

        Args:
            raw_input: Original user message (for IntentResult).
            response_text: Raw LLM response string.

        Returns:
            IntentResult from parsed JSON, or ambiguous on failure.
        """
        _valid_intents = {
            "greet", "book", "ask_info", "confirm",
            "reject", "cancel", "escalate", "ambiguous",
        }

        try:
            cleaned = response_text.strip()

            # Strip markdown code fences if present
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)

            intent_raw = data.get("intent", "ambiguous").lower().strip()
            confidence = float(data.get("confidence", 0.0))

            # Validate intent is one of our known types
            if intent_raw not in _valid_intents:
                logger.warning(
                    "IntentRouter: LLM returned unknown intent '%s' — mapping to ambiguous",
                    intent_raw,
                )
                intent_raw = "ambiguous"

            mode_hint = _intent_to_mode_hint(intent_raw)

            logger.info(
                "IntentRouter: LLM classification | intent=%s | confidence=%.2f | text=%s",
                intent_raw,
                confidence,
                raw_input[:50],
            )

            return IntentResult(
                intent=intent_raw,
                confidence=confidence,
                raw_input=raw_input,
                mode_hint=mode_hint,
            )

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "IntentRouter: failed to parse LLM response | error=%s | response=%s",
                exc,
                response_text[:200],
            )
            return IntentResult(
                intent="ambiguous",
                confidence=0.0,
                raw_input=raw_input,
                mode_hint=None,
            )
