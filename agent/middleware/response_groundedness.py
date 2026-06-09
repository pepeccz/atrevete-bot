"""ResponseGroundednessMiddleware — post-hoc LLM reply scan for hallucination signals.

Change J: hallucination-tolerant-architecture-bundle. REQ-J5.

Runs AFTER the LLM model call (awrap_model_call post-handler). Scans the assistant
reply for two violation types:
  (a) Capitalized multi-word phrases in the reply that look like service/stylist names
      but are NOT found in the `_slot_catalog` token set. These may be hallucinated
      service names not offered by the salon.
  (b) Numeric price patterns (\\d+[.,]?\\d* followed by €/eur/euros).

LOG-ONLY mode at initial deploy. No message blocking or modification.

Performance: word-boundary regex over normalized catalog tokens. Compiled regex
cached per catalog content hash (5-min wall-clock TTL). Overhead target: <5ms/turn.

Design decisions:
  D3 — Position: registered last in base_middleware so its post-handler runs first
       in unwind, seeing the raw assistant reply before any other processing.
  D4 — Token detection: word-boundary regex over lowercased + accent-stripped tokens.
       ~100 catalog tokens fits a single compiled `\\b(token1|token2|...)\\b` pattern.
       Catalog scan checks for capitalized multi-word phrases NOT in the catalog
       (potential hallucinated service names). Heuristic: 2+ consecutive words where
       each starts with a Unicode uppercase letter. False-positive rate is low because
       genuine service/stylist names are capitalized while common words are not.
  D5 — Price detection: `(\\d+[.,]?\\d*\\s*(€|eur|euros))` catches numeric-price patterns.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)

# Price pattern: matches "25 €", "30€", "25.50 eur", "100 euros" etc.
_PRICE_RE = re.compile(
    r"\d+[.,]?\d*\s*(€|eur\b|euros\b)",
    re.IGNORECASE,
)

# Capitalized multi-word phrase pattern (potential service/stylist names).
# Matches two or more consecutive words where each word starts with a Unicode
# uppercase letter. Used for catalog scan (type-a hallucination detection).
# Examples: "Keratina Suprema", "Servicio Inventado XYZ", "Barro Gold Extra"
_CAP_PHRASE_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñA-ZÁÉÍÓÚÜÑ]*(?:\s+[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñA-ZÁÉÍÓÚÜÑ]*)+\b"
)

# Catalog token regex cache: {sha1_hex: (compiled_regex, built_at_ts)}
_REGEX_CACHE: dict[str, tuple[re.Pattern, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _normalize_token(token: str) -> str:
    """Lowercase and strip accents for word-boundary matching."""
    nfkd = unicodedata.normalize("NFKD", token)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _extract_catalog_tokens(catalog_slot: str) -> list[str]:
    """Extract meaningful tokens from the _slot_catalog XML block.

    Extracts service and stylist names by parsing lines from the <catalog> block.
    Skips lines that are only UUIDs, punctuation, or XML tags.
    Returns normalized (lowercased, accent-stripped) multi-char tokens.
    """
    tokens: list[str] = []
    for line in catalog_slot.splitlines():
        # Skip XML tags and empty lines
        line = line.strip()
        if not line or line.startswith("<") or line.startswith(">"):
            continue
        # Strip inline id= annotation
        if " id=" in line:
            line = line[: line.index(" id=")].strip()
        # Skip pure UUID-looking segments
        if re.match(r"^[0-9a-f\-]{8,}$", line, re.IGNORECASE):
            continue
        # Keep multi-word tokens (at least 2 chars after normalization)
        normalized = _normalize_token(line)
        if len(normalized) >= 2:
            tokens.append(normalized)
    return tokens


def _get_or_build_catalog_regex(catalog_slot: str) -> re.Pattern | None:
    """Return a compiled word-boundary regex for catalog tokens, using cached version if fresh.

    Returns None if catalog_slot is empty or no tokens could be extracted.
    """
    if not catalog_slot:
        return None

    content_hash = hashlib.sha1(catalog_slot.encode("utf-8")).hexdigest()
    now = time.monotonic()

    if content_hash in _REGEX_CACHE:
        cached_regex, built_at = _REGEX_CACHE[content_hash]
        if now - built_at < _CACHE_TTL_SECONDS:
            return cached_regex

    tokens = _extract_catalog_tokens(catalog_slot)
    if not tokens:
        return None

    # Build word-boundary alternation pattern
    escaped = [re.escape(t) for t in tokens if t]
    if not escaped:
        return None

    pattern = r"\b(" + "|".join(escaped) + r")\b"
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        logger.debug("ResponseGroundednessMiddleware: failed to compile catalog regex")
        return None

    _REGEX_CACHE[content_hash] = (compiled, now)
    return compiled


class ResponseGroundednessMiddleware(AgentMiddleware):
    """Post-hoc scan of LLM assistant replies for groundedness violations.

    Checks:
      (a) Catalog token scan: warns if the reply contains a capitalized multi-word
          phrase that looks like a service/stylist name but is NOT in the current
          `_slot_catalog` token set (potential hallucinated service name).
      (b) Price regex: warns if the reply contains any numeric price pattern.

    LOG-ONLY mode: no message blocking or modification in this change.
    Hard-block deferred to a follow-up PR after log baseline is established.
    """

    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        # Call the upstream handler FIRST (post-handler position)
        response = await handler(request)

        state = request.state or {}
        catalog_slot = state.get("_slot_catalog") or ""
        conversation_id = state.get("conversation_id", "unknown")

        # Extract assistant reply content
        reply_content: str = ""
        try:
            if response and hasattr(response, "result") and response.result:
                last_msg = response.result[-1]
                if hasattr(last_msg, "content"):
                    reply_content = last_msg.content or ""
        except Exception as exc:
            logger.debug("ResponseGroundednessMiddleware: could not extract reply content: %s", exc)
            return response

        if not reply_content:
            return response

        # (a) Catalog token scan — detect capitalized phrases not in the catalog
        # Heuristic: multi-word capitalized sequences that look like service/stylist
        # names but are absent from the catalog token set may be hallucinations.
        if catalog_slot:
            catalog_tokens = set(_extract_catalog_tokens(catalog_slot))
            cap_phrases = _CAP_PHRASE_RE.findall(reply_content)
            unknown_phrases = [
                phrase for phrase in cap_phrases if _normalize_token(phrase) not in catalog_tokens
            ]
            if unknown_phrases:
                logger.warning(
                    "response.groundedness.violation",
                    extra={
                        "type": "unknown_catalog_token",
                        "conversation_id": conversation_id,
                        "unknown_phrases": unknown_phrases[:3],  # cap at 3 for log size
                    },
                )

        # (b) Price pattern check — straightforward, low false-positive rate
        price_matches = _PRICE_RE.findall(reply_content)
        if price_matches:
            logger.warning(
                "response.groundedness.violation",
                extra={
                    "type": "price_pattern",
                    "conversation_id": conversation_id,
                    "matches": [str(m) for m in price_matches[:3]],  # cap at 3 for log size
                },
            )

        # LOG-ONLY: no modification to response
        return response
