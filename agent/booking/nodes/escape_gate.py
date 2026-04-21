"""
escape_gate — Intent gate at booking subgraph entry.

Detects cancel / escalate / reschedule / check_appointments keywords BEFORE
any resolver runs. On match, emits Command(goto=END, update={...}) to exit
the subgraph into the parent conversation_flow.

Ambiguous turns (no keyword match) fall through to interpret_user_update.

Design ref: design §D3, spec R3.1–R3.8.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langgraph.types import Command

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Escape intent → (target_mode, booking_context_disposition)
# ---------------------------------------------------------------------------

ESCAPE_MAP: dict[str, tuple[str, str]] = {
    "cancel":             ("GENERAL",                "clear"),
    "escalate":           ("ESCALATION",             "preserve"),
    "reschedule":         ("APPOINTMENT_MANAGEMENT", "preserve"),
    "check_appointments": ("APPOINTMENT_MANAGEMENT", "preserve"),
}

# ---------------------------------------------------------------------------
# Keyword patterns per intent
# ---------------------------------------------------------------------------

_CANCEL_PATTERNS = re.compile(
    r"\b(?:"
    r"cancelar?|"
    r"no\s+quiero\s+reservar|"
    r"olvidalo|"
    r"dejalo"
    r")\b",
    re.IGNORECASE,
)

_ESCALATE_PATTERNS = re.compile(
    r"\b(?:"
    r"quiero\s+hablar\s+con\s+(?:una?\s+)?persona|"
    r"hablar\s+con\s+(?:un\s+)?humano|"
    r"asesor(?:a)?|"
    r"quiero\s+(?:un\s+)?asesor|"
    r"derivar"
    r")\b",
    re.IGNORECASE,
)

_RESCHEDULE_PATTERNS = re.compile(
    r"\b(?:"
    r"cambiar?\s+(?:mi\s+)?(?:turno|cita|reserva)|"
    r"reprogramar|"
    r"modificar\s+(?:mi\s+)?(?:turno|cita)"
    r")\b",
    re.IGNORECASE,
)

_CHECK_PATTERNS = re.compile(
    r"\b(?:"
    r"ver\s+mis\s+(?:turnos?|citas?)|"
    r"consultar?\s+(?:mi\s+)?(?:turno|cita)|"
    r"mis\s+reservas?|"
    r"tengo\s+(?:un\s+)?turno"
    r")\b",
    re.IGNORECASE,
)

_PATTERN_MAP: dict[str, re.Pattern] = {
    "cancel": _CANCEL_PATTERNS,
    "escalate": _ESCALATE_PATTERNS,
    "reschedule": _RESCHEDULE_PATTERNS,
    "check_appointments": _CHECK_PATTERNS,
}


def _detect_escape_intent(text: str) -> str | None:
    """Return the first matching escape intent key, or None if no match."""
    for intent, pattern in _PATTERN_MAP.items():
        if pattern.search(text):
            return intent
    return None


async def escape_gate(state: dict[str, Any]) -> dict[str, Any] | Command:
    """Entry gate: detect escape intents; emit Command(goto=END) or fall through.

    P1 stub: always falls through (no keywords matched yet).
    P5 will activate keyword detection.
    """
    user_text: str = state.get("user_message") or ""
    bc: dict[str, Any] = state.get("booking_context") or {}

    intent = _detect_escape_intent(user_text)
    if intent is None:
        logger.debug("escape_gate | no_match | falling_through")
        return {}

    target_mode, disposition = ESCAPE_MAP[intent]
    new_bc = {} if disposition == "clear" else dict(bc)

    logger.info(
        "escape_gate | intent=%s | target_mode=%s | disposition=%s",
        intent,
        target_mode,
        disposition,
    )

    return Command(
        goto="__end__",
        update={"current_mode": target_mode, "booking_context": new_bc},
    )
