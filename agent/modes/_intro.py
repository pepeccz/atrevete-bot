"""Shared helpers for mode nodes migrated to ``create_agent``.

Holds the utilities that used to live on ``BaseModeNode`` and are still
needed once the class is gone: the EU-AI-Act first-turn disclosure prepend
and the ``USE_OPTIMIZED_PROMPTS`` settings flag.
"""

from __future__ import annotations

import logging
import re

from agent.state.schemas import ConversationState
from shared.config import get_settings

logger = logging.getLogger(__name__)


FIRST_TURN_INTRO = "¡Hola! 🌸 Soy Maite, la asistenta virtual con IA de Atrévete Peluquería."

_GREETING_OPENER_PATTERN = re.compile(
    r"^[\s\U0001F300-\U0001FAFF]*"
    r"[¡!]?"
    r"(?:hola|buenas?(?:\s+(?:d[ií]as?|tardes?|noches?))?)"
    r"[^.!?]*"
    r"[.!?]?\s*"
    r"[\U0001F300-\U0001FAFF\s]*",
    re.IGNORECASE,
)
_SELF_INTRO_PATTERN = re.compile(
    r"^(?:soy\s+maite|maite[,.]?\s+(?:tu|la|su)\s+asistent)[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)
_MAX_STRIP_ITERATIONS = 5


def maybe_prepend_intro(
    response_text: str,
    state: ConversationState,
) -> tuple[str, bool]:
    """Prepend the first-turn disclosure unless it was already handled.

    Returns a tuple ``(final_text, disclosure_sent)``. ``disclosure_sent`` is
    True whenever the intro either was just added or was already present in
    history — the caller writes it back to ``state["ai_disclosure_sent"]``.

    Strips any LLM-generated self-intro ("hola soy maite…") before prepending
    the canonical one so the message never repeats the disclosure twice.
    """
    if state.get("ai_disclosure_sent", False):
        return response_text, False

    for msg in state.get("messages", []):
        if msg.get("role") == "assistant" and "soy maite" in (msg.get("content") or "").lower():
            return response_text, True

    any_stripped = False
    for _ in range(_MAX_STRIP_ITERATIONS):
        prev = response_text
        response_text = _GREETING_OPENER_PATTERN.sub("", response_text).lstrip()
        response_text = _SELF_INTRO_PATTERN.sub("", response_text).lstrip()
        if response_text == prev:
            break
        any_stripped = True
    if any_stripped:
        logger.debug("maybe_prepend_intro: stripped LLM self-intro from first-turn response")

    if response_text.startswith(FIRST_TURN_INTRO[:20]):
        return response_text, True
    if FIRST_TURN_INTRO in response_text:
        return response_text, True

    return f"{FIRST_TURN_INTRO} {response_text}", True


def use_optimized_prompts() -> bool:
    """Return True when the layered-prompt assembly is enabled.

    Defaults to True when settings can't be loaded (matches the legacy
    ``BaseModeNode._use_optimized_prompts`` behaviour).
    """
    try:
        return bool(get_settings().USE_OPTIMIZED_PROMPTS)
    except Exception:
        return True


__all__ = ["FIRST_TURN_INTRO", "maybe_prepend_intro", "use_optimized_prompts"]
