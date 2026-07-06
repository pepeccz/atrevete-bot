"""ResponseGroundednessMiddleware — post-hoc LLM reply scan for hallucination signals.

Change J: hallucination-tolerant-architecture-bundle. REQ-J5.
Change F1: confirmation-grounding gate (this is now a BLOCKING gate for BOOKING
confirmations only).

Runs AFTER the LLM model call (awrap_model_call post-handler). Scans the assistant
reply for the following violation types:
  (a) Capitalized multi-word phrases in the reply that look like service/stylist names
      but are NOT found in the `_slot_catalog` token set. These may be hallucinated
      service names not offered by the salon. — LOG-ONLY.
  (b) Numeric price patterns (\\d+[.,]?\\d* followed by €/eur/euros). — LOG-ONLY.
  (c) BOOKING confirmation phrasing ("te he confirmado la cita", "reserva confirmada",
      "ya está tu cita", …) that is NOT backed by a successful `book` OR
      `manage_appointments` tool result in the CURRENT turn. — BLOCKING.
  (d) MUTATION confirmation phrasing for cancel/reschedule ("cita cancelada",
      "cita reprogramada", …). — LOG-ONLY (see BLOCKER-1 below).

SCOPE DECISION (BLOCKER-1 — REVISED): the BLOCKING gate covers BOOKING confirmation
phrasing regardless of which management tool triggered it. `manage_appointments`
returns a plain STRING (the message text), not a JSON ToolResponse. We detect success
by checking the string is non-empty and does NOT contain error-marker substrings
(_MANAGE_ERROR_MARKERS). This allows legitimate cancel/reschedule turns whose reply
uses booking-flavored wording ("te he confirmado…", "listo… la cita") to pass through
without being rewritten, while still blocking a hallucinated confirmation that has no
backing tool result at all.

Checks (a), (b) and (d) are LOG-ONLY. Check (c) is the only BLOCKING gate: when
BOOKING confirmation phrasing is present but no backing successful `book` OR
`manage_appointments` result proves an action happened IN THIS TURN, the assistant
message content is REPLACED with a safe castellano fallback so the customer never
receives a hallucinated confirmation.

Performance: word-boundary regex over normalized catalog tokens. Compiled regex
cached per catalog content hash (5-min wall-clock TTL). Overhead target: <5ms/turn.

Design decisions:
  D3 — Position: registered last in base_middleware so its post-handler runs first
       in unwind, seeing the raw assistant reply before any other processing.
  D4 — Token detection: word-boundary regex over lowercased + accent-stripped tokens.
  D5 — Price detection: `(\\d+[.,]?\\d*\\s*(€|eur|euros))` catches numeric-price patterns.
  D6 — Booking gate (F1): a tight, conservative regex matches new-booking confirmation
       phrasing without matching questions ("¿confirmas?"). When matched, the gate
       looks for a backing `book` ToolMessage produced IN THIS TURN ONLY (see D7) with
       status="ok" + non-empty appointment_id. Absent that proof, the gate FAILS SAFE
       and replaces the reply. Genuine confirmations pass untouched.
  D7 — Turn-bounding (BLOCKER-2): the backing-result search is bounded to the CURRENT
       model-call cycle. Primary path: correlate by tool_call_id — collect tool_calls
       on the AIMessage(s) in `response.result`, then accept ONLY a `book` ToolMessage
       whose tool_call_id matches one of those tool_calls. Fallback (when correlation is
       not feasible): slice the combined (state messages + response.result) sequence to
       only the messages AFTER the last HumanMessage, and look there. This prevents a
       real booking from an EARLIER turn green-lighting a later hallucinated
       confirmation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# F1 — Confirmation-grounding gate
# ---------------------------------------------------------------------------

# Tool whose successful result legitimizes a BOOKING confirmation message.
_BOOK_TOOL_NAME = "book"
# Tool that handles cancel/reschedule. Returns a plain STRING (not JSON).
# Success is detected by substring absence — see _has_successful_manage_result_this_turn.
_MANAGE_TOOL_NAME = "manage_appointments"

# Error-signal substrings for manage_appointments plain-string results (case-insensitive).
# If ANY of these appears in the ToolMessage content, the result is treated as a failure.
# Derived from the real failure strings in agent/tools/manage_appointments_tool.py
# (e.g. "No pude cancelar la cita.", "Hubo un problema al ...", "El identificador ... no es válido.").
_MANAGE_ERROR_MARKERS: tuple[str, ...] = (
    "no se ha podido",
    "no he podido",
    "no pude",
    "hubo un problema",
    "no encontr",
    "no existe",
    "no puedo",
    "no es válido",
    "no consta",
    "no reconozco",
    "no tienes citas",
    "necesito el id",
    "error",
    "no hay ninguna cita",
    "no figura",
)

# --- BOOKING confirmation phrasing (BLOCKING) ------------------------------
# Spanish, case-insensitive. Conservative: must NOT match questions such as
# "¿confirmas?" or "¿te lo confirmo?" (interrogative), only assertive statements that a
# NEW booking is already done.
#
# NOTE: This constant is duplicated (kept in sync) in
# tests/e2e/harness/assert_claim_backend.py so the regression harness flags the same
# class of hallucination. A drift-guard unit test asserts the two sources are identical.
# If you change this pattern, update that file too.
_BOOKING_CONFIRMATION_PATTERNS: tuple[str, ...] = (
    # "te he confirmado", "te queda reservada", "te he agendado", "te confirmo la cita ..."
    r"te\s+(he\s+|queda\s+)?(confirmad|reservad|agendad)\w*",
    r"reserva\s+confirmada",
    # "tu cita ya está confirmada/reservada" (allow a few intervening words; questions
    # like "¿la cita?" do not match because there is no confirmation verb after).
    r"cita\s+(?:\w+\s+){0,3}(confirmada|reservada|agendada)",
    # "¡Listo! tu cita ...", "Listo, queda tu cita ..."
    r"^\s*¡?listo!?\b.*cit",
    # "ya está tu cita", "tu cita queda ...", "quedas anotad@ ..."
    r"ya\s+est[áa]\s+tu\s+cita",
    r"tu\s+cita\s+queda",
    r"quedas\s+anotad\w*",
    # "cita ... agendada" / "cita agendada"
    r"cita\s+(?:\w+\s+){0,3}agendada",
    # "¡Hecho!" / "hecho" only when near appointment context (cita/reserva nearby).
    r"¡?hecho!?(?:\W+\w+){0,4}\W+(?:cita|reserva)",
    r"(?:cita|reserva)(?:\W+\w+){0,4}\W+¡?hecho!?",
)

_BOOKING_CONFIRMATION_RE = re.compile(
    "|".join(f"(?:{p})" for p in _BOOKING_CONFIRMATION_PATTERNS),
    re.IGNORECASE | re.MULTILINE,
)

# --- MUTATION confirmation phrasing (LOG-ONLY) -----------------------------
# Cancel/reschedule confirmation phrasing. Observed but NOT rewritten (BLOCKER-1):
# manage_appointments returns a plain string so we cannot verify the backing result.
_MUTATION_CONFIRMATION_PATTERNS: tuple[str, ...] = (
    r"cita\s+(?:\w+\s+){0,3}(cancelada|cambiada|modificada|reprogramada)",
    r"(?:cancelada|reprogramada|modificada)\s+(?:tu\s+)?cita",
)

_MUTATION_CONFIRMATION_RE = re.compile(
    "|".join(f"(?:{p})" for p in _MUTATION_CONFIRMATION_PATTERNS),
    re.IGNORECASE | re.MULTILINE,
)

# Safe castellano fallback substituted when a hallucinated BOOKING confirmation is
# blocked. Booking-specific (neutral castellano, no voseo).
_CONFIRMATION_FALLBACK_MESSAGE = (
    "Perdona, déjame confirmar la disponibilidad antes de cerrar la cita. "
    "¿Te confirmo las opciones?"
)

# --- F1 v3 — bare-proposal template guard (BLOCKING, REQ-F1-1) -------------
# Turn-A proposal template ("te lo dejo" + a time/date token). Legit Turn-A phrasing
# (booking_flow.md, "Puerta de confirmación") always ends in "¿Te lo confirmo?"; the
# phantom variant is the SAME template MINUS the trailing "?". This guard fires
# regardless of any this-turn tool backing (REQ-F1-1) — it is not part of the shared
# _BOOKING_CONFIRMATION_PATTERNS tuple synced with the harness (drift-guard scope
# unchanged; see module docstring D7 / test_booking_regex_source_matches_harness_helper).
_BARE_PROPOSAL_PHRASE_RE = re.compile(r"te\s+lo\s+dejo", re.IGNORECASE)
_TIME_OR_DATE_TOKEN_RE = re.compile(
    r"\d{1,2}[:.]\d{2}"  # "14:30" / "14.30"
    r"|\d{1,2}\s+de\s+[a-záéíóúñ]+"  # "9 de julio"
    r"|\b(lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\b",
    re.IGNORECASE,
)


def _matches_bare_proposal(reply_content: str) -> bool:
    """True for the Turn-A proposal template ("te lo dejo" + time/date) with no "?".

    REQ-F1-1: counts a match ONLY when the reply has no "?", regardless of this-turn
    tool backing — a proposal template phrased as a statement (no question) is flagged
    unconditionally.
    """
    if not isinstance(reply_content, str) or not reply_content:
        return False
    if "?" in reply_content:
        return False
    if not _BARE_PROPOSAL_PHRASE_RE.search(reply_content):
        return False
    return bool(_TIME_OR_DATE_TOKEN_RE.search(reply_content))


# --- F1 v3 — bare-completion phrase guard (BLOCKING, REQ-F1-2) -------------
# Closing/completion phrases ("queda todo listo", "todo listo", "ya está todo") that
# assert completion without a "?" and without any failure/negation marker nearby. Also
# fires regardless of this-turn tool backing (REQ-F1-2) and lives in the middleware
# only — NOT part of the shared drift-guard tuple.
_COMPLETION_PHRASE_RE = re.compile(
    r"queda\s+todo\s+listo|\btodo\s+listo\b|ya\s+est[áa]\s+todo\b",
    re.IGNORECASE,
)

# Failure/negation marker set for the completion-phrase guard: reuses
# _MANAGE_ERROR_MARKERS plus the literals "pero" and "no se ha" (REQ-F1-2).
_COMPLETION_NEGATION_MARKERS: tuple[str, ...] = (*_MANAGE_ERROR_MARKERS, "pero", "no se ha")

# Friendly, neutral closing substituted when a bare-completion phantom is blocked. Does
# NOT invite re-booking (unlike _CONFIRMATION_FALLBACK_MESSAGE) — it neither asserts nor
# denies a booking, so the accepted residual FP (post-real-booking closing pleasantry,
# REQ-F1-7) becomes a harmless warm closing instead of a flow-corrupting re-booking
# prompt. Castellano, no voseo (project convention).
_COMPLETION_FALLBACK_MESSAGE = "¡Un placer! Si necesitas cualquier otra cosa, aquí me tienes 😊"


def _is_bare_completion(reply_content: str) -> bool:
    """True for a bare completion-phrase phantom (REQ-F1-2).

    Counts a match ONLY when the message (a) has NO "?" AND (b) contains NONE of the
    failure/negation marker set (_COMPLETION_NEGATION_MARKERS). A completion phrase that
    has a "?" OR contains a failure/negation marker is exempted, independent of tool
    backing.
    """
    if not isinstance(reply_content, str) or not reply_content:
        return False
    if "?" in reply_content:
        return False
    if not _COMPLETION_PHRASE_RE.search(reply_content):
        return False
    lowered = reply_content.lower()
    return not any(marker in lowered for marker in _COMPLETION_NEGATION_MARKERS)

# Price pattern: matches "25 €", "30€", "25.50 eur", "100 euros" etc.
_PRICE_RE = re.compile(
    r"\d+[.,]?\d*\s*(€|eur\b|euros\b)",
    re.IGNORECASE,
)

# Capitalized multi-word phrase pattern (potential service/stylist names).
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


def _reply_has_booking_confirmation(reply_content: str) -> str | None:
    """Return the first matched BOOKING confirmation phrase, or None.

    Conservative: matches assertive new-booking confirmation statements, not questions.
    """
    if not isinstance(reply_content, str) or not reply_content:
        return None
    match = _BOOKING_CONFIRMATION_RE.search(reply_content)
    return match.group(0) if match else None


def _reply_has_mutation_confirmation(reply_content: str) -> str | None:
    """Return the first matched MUTATION (cancel/reschedule) confirmation phrase, or None."""
    if not isinstance(reply_content, str) or not reply_content:
        return None
    match = _MUTATION_CONFIRMATION_RE.search(reply_content)
    return match.group(0) if match else None


def _parse_tool_message_payload(message: ToolMessage) -> dict[str, Any] | None:
    """Best-effort parse of a ToolMessage's JSON content into a dict.

    `book`'s ToolMessage.content is a JSON string (ToolResponse.model_dump_json).
    Returns None when content is missing or not a JSON object.
    """
    content = getattr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_successful_book_result(payload: dict[str, Any]) -> bool:
    """True when a `book` ToolResponse proves a real appointment was created.

    Requires status == "ok" AND a non-empty payload.appointment_id.
    """
    if payload.get("status") != "ok":
        return False
    inner = payload.get("payload")
    if not isinstance(inner, dict):
        return False
    appointment_id = inner.get("appointment_id")
    return bool(appointment_id) and isinstance(appointment_id, str)


def _collect_current_turn_book_call_ids(result_messages: list[Any] | None) -> set[str]:
    """Collect tool_call ids for `book` calls emitted by AIMessage(s) in this cycle.

    `response.result` holds the messages produced by THIS model-call cycle. An AIMessage
    that requested a `book` tool exposes them via `.tool_calls` (list of dicts with
    keys name/args/id). We collect the ids of `book` calls so we can correlate them with
    their ToolMessage results (turn-bounding by tool_call_id).
    """
    call_ids: set[str] = set()
    if not result_messages:
        return call_ids
    for message in result_messages:
        tool_calls = getattr(message, "tool_calls", None)
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            # tool_calls entries are dicts: {"name": ..., "args": ..., "id": ...}
            if not isinstance(call, dict):
                continue
            if call.get("name") != _BOOK_TOOL_NAME:
                continue
            call_id = call.get("id")
            if isinstance(call_id, str) and call_id:
                call_ids.add(call_id)
    return call_ids


def _has_correlated_book_result(messages: list[Any] | None, book_call_ids: set[str]) -> bool:
    """True when a successful `book` ToolMessage correlates to a this-turn book call id.

    Correlation: the ToolMessage.tool_call_id must be one of `book_call_ids` AND the
    payload must be a successful book result. This is the strongest turn-bounding signal.
    """
    if not messages or not book_call_ids:
        return False
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        if getattr(message, "name", None) != _BOOK_TOOL_NAME:
            continue
        tool_call_id = getattr(message, "tool_call_id", None)
        if tool_call_id not in book_call_ids:
            continue
        payload = _parse_tool_message_payload(message)
        if payload is not None and _is_successful_book_result(payload):
            return True
    return False


def _slice_after_last_human(messages: list[Any]) -> list[Any]:
    """Return only the messages AFTER the last HumanMessage in the sequence.

    Fallback turn-bounding (D7): when tool_call_id correlation is not feasible, the
    current turn is approximated as everything after the most recent customer message.
    If no HumanMessage is present, the whole sequence is returned (best effort).
    """
    last_human_idx = -1
    for idx, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            last_human_idx = idx
    if last_human_idx < 0:
        return messages
    return messages[last_human_idx + 1 :]


def _has_successful_book_in_messages(messages: list[Any]) -> bool:
    """True when any successful `book` ToolMessage is present in the given slice."""
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        if getattr(message, "name", None) != _BOOK_TOOL_NAME:
            continue
        payload = _parse_tool_message_payload(message)
        if payload is not None and _is_successful_book_result(payload):
            return True
    return False


def _has_successful_manage_result_this_turn(current_turn_messages: list[Any]) -> bool:
    """True when a successful `manage_appointments` ToolMessage is present in the current turn.

    manage_appointments returns a plain STRING (not JSON). Success detection:
      - content is a non-empty string
      - content does NOT contain any of _MANAGE_ERROR_MARKERS (case-insensitive)

    Turn-bounding: caller MUST pass the already-computed current-turn slice (the same
    set used by the book check) so a manage success from a prior turn never counts.

    Defensive: handles non-str content and missing name attribute gracefully.
    """
    if not current_turn_messages:
        return False
    for message in current_turn_messages:
        if not isinstance(message, ToolMessage):
            continue
        if getattr(message, "name", None) != _MANAGE_TOOL_NAME:
            continue
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            continue
        content_lower = content.lower()
        if any(marker in content_lower for marker in _MANAGE_ERROR_MARKERS):
            continue
        # Non-empty content with no error markers → successful manage result
        return True
    return False


def _has_backing_tool_result_this_turn(
    *,
    history: list[Any],
    result_messages: list[Any],
) -> bool:
    """Turn-bounded check for a successful `book` OR `manage_appointments` result.

    Primary path (D7): correlate by tool_call_id for `book`. Collect `book` tool_call
    ids from the AIMessage(s) in `result_messages` (this cycle) and accept ONLY a `book`
    ToolMessage whose tool_call_id matches AND whose payload is a successful book result.

    Fallback: when no `book` tool_call ids are found on this cycle's AIMessages (e.g.
    the result objects do not expose tool_calls), slice the combined sequence to the
    messages AFTER the last HumanMessage and look there for either:
      - a successful `book` ToolMessage (JSON payload), OR
      - a successful `manage_appointments` ToolMessage (plain-string, no error markers).

    This keeps the search bounded to the current turn and prevents stale prior-turn
    results from green-lighting a later hallucinated confirmation.
    """
    combined: list[Any] = [*history, *result_messages]

    book_call_ids = _collect_current_turn_book_call_ids(result_messages)
    if book_call_ids:
        # Primary path: tool_call_id-correlated book check.
        # Also compute current-turn slice for manage check (turn-bounded same way).
        current_turn = _slice_after_last_human(combined)
        return _has_correlated_book_result(
            combined, book_call_ids
        ) or _has_successful_manage_result_this_turn(current_turn)

    # Fallback: turn-bound by slicing after the last HumanMessage.
    current_turn = _slice_after_last_human(combined)
    return _has_successful_book_in_messages(
        current_turn
    ) or _has_successful_manage_result_this_turn(current_turn)


class ResponseGroundednessMiddleware(AgentMiddleware):
    """Post-hoc scan of LLM assistant replies for groundedness violations.

    Checks:
      (a) Catalog token scan: warns if the reply contains a capitalized multi-word
          phrase that looks like a service/stylist name but is NOT in the current
          `_slot_catalog` token set. LOG-ONLY.
      (b) Price regex: warns if the reply contains any numeric price pattern. LOG-ONLY.
      (c) BOOKING confirmation gate (F1): BLOCKING. When the reply asserts a NEW booking
          is confirmed but no successful `book` tool result backs it IN THE CURRENT
          TURN, the reply content is REPLACED with a safe castellano fallback.
      (d) MUTATION confirmation (cancel/reschedule): LOG-ONLY. We cannot verify
          manage_appointments success (plain-string return), so we only warn.

    Checks (a), (b) and (d) are LOG-ONLY. Check (c) is the only BLOCKING gate.
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
        reply_content: Any = ""
        last_msg: Any = None
        try:
            if response and hasattr(response, "result") and response.result:
                last_msg = response.result[-1]
                if hasattr(last_msg, "content"):
                    reply_content = last_msg.content or ""
        except Exception as exc:
            logger.debug("ResponseGroundednessMiddleware: could not extract reply content: %s", exc)
            return response

        # (FIX MINOR-1) Content-type guard: AIMessage.content can be a list of parts for
        # some providers. Only run the string-based gate/regexes when it is a plain str.
        if not isinstance(reply_content, str) or not reply_content:
            return response

        # (c) BOOKING confirmation grounding gate (BLOCKING) — must run before LOG-ONLY
        # checks so a hallucinated booking confirmation is replaced regardless of noise.
        gated = self._enforce_booking_confirmation_gate(
            request=request,
            response=response,
            reply_content=reply_content,
            last_msg=last_msg,
            conversation_id=conversation_id,
        )
        if gated is not None:
            return gated

        # (d) MUTATION confirmation (cancel/reschedule) — LOG-ONLY (BLOCKER-1).
        mutation_phrase = _reply_has_mutation_confirmation(reply_content)
        if mutation_phrase is not None:
            logger.warning(
                "unbacked_mutation_confirmation_observed",
                extra={
                    "type": "unbacked_mutation_confirmation",
                    "conversation_id": conversation_id,
                    "matched_phrase": mutation_phrase,
                },
            )

        # (a) Catalog token scan — detect capitalized phrases not in the catalog
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

    def _enforce_booking_confirmation_gate(
        self,
        *,
        request: ModelRequest,
        response: ModelResponse,
        reply_content: str,
        last_msg: Any,
        conversation_id: str,
    ) -> ModelResponse | None:
        """BLOCKING gate: replace hallucinated BOOKING confirmations.

        Returns the (mutated) ModelResponse when the reply was a hallucinated booking
        confirmation that we blocked, or None when no action was taken (no booking
        confirmation phrasing, or a genuine this-turn `book` result exists).

        Fail-safe policy: when booking confirmation phrasing is present but we cannot
        prove a backing `book` result in the CURRENT turn, we BLOCK. We only skip
        blocking when there is genuinely no booking phrasing, or a successful book result
        is found in this turn (correlated by tool_call_id, or sliced after the last
        HumanMessage as a fallback).

        F1 v3 — two additional guards run BEFORE the tool-backing check and fire
        UNCONDITIONALLY (regardless of this-turn tool backing, REQ-F1-1/F1-2):
          - `_matches_bare_proposal` (Turn-A "te lo dejo" template with no "?")
          - `_is_bare_completion` (closing/completion phrase with no "?" and no
            failure/negation marker)
        Each uses its own branch-specific fallback (REQ-F1-7): the completion-phrase
        branch uses `_COMPLETION_FALLBACK_MESSAGE`, never the re-booking-invite
        `_CONFIRMATION_FALLBACK_MESSAGE` used by the proposal-template and legacy
        booking-assertion branches.
        """
        if _matches_bare_proposal(reply_content):
            return self._block_and_replace(
                response=response,
                last_msg=last_msg,
                conversation_id=conversation_id,
                matched_phrase="bare_proposal_template",
                fallback_message=_CONFIRMATION_FALLBACK_MESSAGE,
            )

        if _is_bare_completion(reply_content):
            return self._block_and_replace(
                response=response,
                last_msg=last_msg,
                conversation_id=conversation_id,
                matched_phrase="bare_completion_phrase",
                fallback_message=_COMPLETION_FALLBACK_MESSAGE,
            )

        matched_phrase = _reply_has_booking_confirmation(reply_content)
        if matched_phrase is None:
            # No booking confirmation phrasing → never block.
            return None

        # Gather candidate messages: current history (where past tool results live) plus
        # this cycle's freshly produced messages. Defensive against missing/None state.
        state = request.state or {}
        history: list[Any] = []
        raw_history = state.get("messages")
        if isinstance(raw_history, list):
            history = raw_history
        result_messages: list[Any] = []
        raw_result = getattr(response, "result", None)
        if isinstance(raw_result, list):
            result_messages = raw_result

        if _has_backing_tool_result_this_turn(history=history, result_messages=result_messages):
            # Genuine this-turn booking confirmation — leave untouched.
            return None

        # Hallucinated confirmation: replace the reply content with a safe fallback.
        return self._block_and_replace(
            response=response,
            last_msg=last_msg,
            conversation_id=conversation_id,
            matched_phrase=matched_phrase,
            fallback_message=_CONFIRMATION_FALLBACK_MESSAGE,
        )

    @staticmethod
    def _block_and_replace(
        *,
        response: ModelResponse,
        last_msg: Any,
        conversation_id: str,
        matched_phrase: str,
        fallback_message: str,
    ) -> ModelResponse:
        """Log the block and replace `last_msg.content` with `fallback_message`.

        Shared by all three blocking branches (bare-proposal, bare-completion, legacy
        booking-assertion) so the replace-and-log mechanics stay identical; only the
        fallback message and matched-phrase label differ per branch (REQ-F1-7).
        """
        logger.error(
            "hallucinated_confirmation_blocked",
            extra={
                "type": "hallucinated_confirmation",
                "conversation_id": conversation_id,
                "matched_phrase": matched_phrase,
            },
        )

        if last_msg is not None and hasattr(last_msg, "content"):
            try:
                last_msg.content = fallback_message
                return response
            except Exception as exc:  # pragma: no cover — extremely defensive
                logger.error(
                    "hallucinated_confirmation_block_failed",
                    extra={"conversation_id": conversation_id, "error": str(exc)},
                )
        # If we could not rewrite the message in place, we have no other message handle.
        # Log and return response so we never crash the turn.
        return response
