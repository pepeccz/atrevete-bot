"""Deterministic audience-disambiguation guard for QA turn-1 results.

Catches the class of bug where the agent prematurely resolves to a
gendered haircut service (e.g. "Corte Dama") on an audience-ambiguous
opening message ("quiero cortarme el pelo"), BEFORE the customer has
stated who the haircut is for.

BUG PATTERN (reproduced 2026-06-25):
    Customer: "Hola, quiero cortarme el pelo"
    Agent (WRONG): calls update_booking(services=["corte de mujer"]) on turn 1
                   and offers concrete availability for "Corte Dama".
    Agent (RIGHT): asks "¿Es para ti, para un hombre o para un niño?"

Two independent checks compose the verdict:

  Check 1 — premature_tool_call (primary, most precise):
      ANY call to update_booking / check_availability / get_next_available_options
      whose serialized arguments match a gendered haircut pattern → FAIL.
      This catches the exact reproduced bug at the tool-evidence level.

  Check 2 — response_decides_service (secondary):
      The agent response text contains a gendered service name (e.g. "corte de
      mujer") AND that mention appears in a booking / availability context (not
      purely inside a clarifying question). Heuristic: a "decided context"
      pattern fires within ±200 chars of the gendered service match → FAIL.
      Rationale: a response like "¿Sería para corte de mujer o de hombre?" does
      NOT fire because no decided-context pattern (te anoto, disponibilidad, slot
      time, etc.) appears near the match.

PASS condition (clarifying_question):
    The agent response contains a question asking who the service is for,
    covering patterns like "para ti", "para quién", "¿para un hombre o mujer?".
    The helper returns pass=True when no FAIL conditions fired. The presence
    of a clarifying question is recorded in the evidence but is NOT required
    for a pass (benefit of the doubt for responses that simply do not fire any
    fail trigger).

Usage (as a library):
    from tests.e2e.harness.assert_audience_disambiguation import check_audience_disambiguation
    result = check_audience_disambiguation(turn_result)
    # result["pass"]    -> True | False
    # result["verdict"] -> "pass" | "fail"
    # result["reasons"] -> list[str]  (empty when passing)
    # result["evidence"] -> dict with raw matched fragments

Usage (as CLI):
    python tests/e2e/harness/assert_audience_disambiguation.py --turn-file <path>

    Reads a turn-result JSON produced by:
        python tests/e2e/harness/qa_turn_helper.py turn --conversation-id <uuid> ...

    Outputs JSON to stdout. Exit codes:
        0 — pass (no audience-disambiguation violation detected)
        1 — error (bad argument / unreadable file)
        3 — fail (audience-disambiguation violation detected)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Heuristics: gendered haircut service names
#
# Covers:
#   "corte de mujer", "corte dama", "corte de dama", "corte señora",
#   "corte de señora", "corte caballero", "corte de caballero",
#   "corte de hombre", "corte hombre"
#
# Does NOT match bare verb forms ("cortarse el pelo", "quiero un corte") or
# dimension-neutral names ("corte", "cortar").
#
# Tunable: add additional gendered aliases inside the alternation group.
# ---------------------------------------------------------------------------
_GENDERED_SERVICE_RE = re.compile(
    r"corte\s+(?:de\s+)?(?:mujer|dama|se[ñn]ora|caballero|hombre)",
    re.IGNORECASE,
)

# A flat list of the canonical service names covered above (used for logging).
_GENDERED_SERVICE_NAMES: tuple[str, ...] = (
    "corte de mujer",
    "corte dama",
    "corte de dama",
    "corte señora",
    "corte de señora",
    "corte caballero",
    "corte de caballero",
    "corte de hombre",
    "corte hombre",
)

# ---------------------------------------------------------------------------
# Heuristics: "decided" context patterns
#
# These patterns fire when the gendered service name appears in a booking /
# availability-offering context, not just as a clarifying-question option.
#
# Patterns:
#   - Booking confirmation verbs: "te anoto", "te reservo", "quedas anotad*",
#     "voy a anotar/reservar/agendar"
#   - Availability offering: "hay disponibilidad", "hay hueco", "hay hora",
#     "tenemos disponibilidad/hueco/hora", "disponibilidad para", "libre el/para"
#   - Slot presentation: DayName + optional "a las" + HH:MM (concrete slot offer)
#
# The check is applied within a ±200-char window around the gendered service
# match to reduce cross-sentence false positives.
#
# Tunable: extend the alternation in _DECIDED_CONTEXT_RE for new patterns.
# ---------------------------------------------------------------------------
_DECIDED_CONTEXT_RE = re.compile(
    r"(?:"
    r"te\s+(?:he\s+)?(?:anot[ao]|reserv[ao]|agend[ao])"
    r"|quedas?\s+anotad"
    r"|voy\s+a\s+(?:anotar|reservar|agendar)"
    r"|hay\s+(?:disponibilidad|hueco|hora)"
    r"|tenemos\s+(?:disponibilidad|hueco|hora|algo\s+disponible)"
    r"|disponibilidad\s+para"
    r"|libre\s+(?:el|para|los)"
    r"|(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[áa]bado|domingo)"
    r"\s+(?:a\s+las\s+)?\d{1,2}:\d{2}"
    r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Heuristics: clarifying question about audience
#
# The agent MUST ask who the service is for before resolving to a gendered
# service. These patterns constitute valid disambiguating questions.
#
# Patterns:
#   - "para ti" / "para vos" / "para quién"
#   - "¿quién?" / "¿para quién?" / "¿a quién?"
#   - "¿es para ti?" / "¿es para un hombre?" / "¿es para una mujer?"
#   - Explicit multi-audience options within ±40 chars:
#     "hombre ... mujer" or "mujer ... hombre" (bot listing options)
#   - "¿a quién le cortamos?" / "para quién es" / "para quién va"
#   - "¿el corte es para ...?"
#
# Tunable: add more regional phrasings inside the alternation group.
# ---------------------------------------------------------------------------
_CLARIFYING_QUESTION_RE = re.compile(
    r"(?:"
    r"para\s+(?:ti|vos|qui[eé]n)"
    r"|¿\s*(?:para\s+)?qui[eé]n"
    r"|¿\s*(?:es\s+)?para\s+(?:ti|vos|un[ao]?\s+(?:hombre|mujer|ni[ñn][ao]|chic[ao]))"
    r"|(?:hombre|caballero).{0,40}(?:mujer|dama|ni[ñn][ao])"
    r"|(?:mujer|dama|ni[ñn][ao]).{0,40}(?:hombre|caballero)"
    r"|¿\s*a\s+qui[eé]n\s+(?:le|vamos|vas)"
    r"|para\s+qui[eé]n\s+(?:es|ser[aá]|va)\b"
    r"|¿\s*(?:el|la)\s+corte\s+es\s+para"
    r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Tool names that should NOT be called with a gendered service before the
# customer has stated the intended audience.
# ---------------------------------------------------------------------------
_PREMATURE_TOOL_NAMES: frozenset[str] = frozenset(
    {"update_booking", "check_availability", "get_next_available_options"}
)


def _serialise_args(args: Any) -> str:
    """Flatten tool arguments to a lowercase string for pattern matching.

    Converts dicts to compact JSON so nested lists/strings are covered by
    the regex scan. Falls back to str() for unexpected types.
    """
    if isinstance(args, dict):
        return json.dumps(args, ensure_ascii=False, separators=(",", ":")).lower()
    if isinstance(args, str):
        return args.lower()
    return str(args).lower()


def check_audience_disambiguation(turn_result: dict[str, Any]) -> dict[str, Any]:
    """Check that a turn-1 result asks for audience instead of deciding prematurely.

    Designed to run on the first turn of an audience-ambiguous booking request
    (e.g. "quiero cortarme el pelo") BEFORE the customer has stated the intended
    audience (adult_female / adult_male / child).

    Args:
        turn_result: Dict as returned by qa_turn_helper.py ``turn`` subcommand:
            {
                "agent_response": str,
                "timed_out": bool,
                "response_latency_ms": int,
                "tool_evidence": [
                    {
                        "tool_name": str,
                        "arguments": dict,
                        "result": dict,
                        "source": str,
                        "timestamp": str,
                    },
                    ...
                ],
            }

    Returns:
        {
            "pass": bool,           # True iff no FAIL conditions fired
            "verdict": "pass" | "fail",
            "reasons": list[str],   # Human-readable failure reasons (empty on pass)
            "evidence": {
                "premature_tool_calls": list[dict],    # tool calls that fired the rule
                "decided_response_match": str | None,  # matched phrase from response text
                "clarifying_question_match": str | None,  # matched phrase if found
            },
        }
    """
    reasons: list[str] = []

    agent_response: str = turn_result.get("agent_response") or ""
    tool_evidence: list[dict[str, Any]] = turn_result.get("tool_evidence") or []

    # -----------------------------------------------------------------------
    # Check 1: premature tool call with gendered service in arguments
    # -----------------------------------------------------------------------
    premature_tool_calls: list[dict[str, Any]] = []
    for entry in tool_evidence:
        if not isinstance(entry, dict):
            continue
        tool_name: str = str(entry.get("tool_name") or "")
        if tool_name not in _PREMATURE_TOOL_NAMES:
            continue
        args_str = _serialise_args(entry.get("arguments") or {})
        m = _GENDERED_SERVICE_RE.search(args_str)
        if m:
            premature_tool_calls.append(
                {
                    "tool_name": tool_name,
                    "matched_service": m.group(0),
                    "arguments_excerpt": args_str[:400],
                }
            )

    if premature_tool_calls:
        names_and_services = [
            f"{e['tool_name']}(service={e['matched_service']!r})" for e in premature_tool_calls
        ]
        reasons.append(
            f"premature tool call with gendered service before audience stated: "
            f"{', '.join(names_and_services)}"
        )

    # -----------------------------------------------------------------------
    # Check 2: response text decides a gendered service
    #
    # A response "decides" a gendered service when it mentions the service name
    # AND that mention is in a booking / availability-offering context (decided-
    # context pattern fires within ±200 chars of the service name match).
    #
    # A mention purely inside a clarifying question like "¿Sería corte de mujer
    # o de hombre?" does NOT fire because no decided-context pattern (booking
    # verb, availability phrase, or slot time) appears near the mention.
    # -----------------------------------------------------------------------
    decided_match: str | None = None
    gendered_in_response = _GENDERED_SERVICE_RE.search(agent_response)
    if gendered_in_response:
        start = max(0, gendered_in_response.start() - 200)
        end = min(len(agent_response), gendered_in_response.end() + 200)
        window = agent_response[start:end]
        ctx_match = _DECIDED_CONTEXT_RE.search(window)
        if ctx_match:
            decided_match = gendered_in_response.group(0)
            reasons.append(
                f"response text decides a gendered service without audience clarification: "
                f"found {decided_match!r} near booking/availability context "
                f"(context fragment: {ctx_match.group(0)!r})"
            )

    # -----------------------------------------------------------------------
    # Clarifying question evidence (recorded but does not override FAIL)
    # -----------------------------------------------------------------------
    clarifying_match = _CLARIFYING_QUESTION_RE.search(agent_response)
    clarifying_match_str: str | None = (
        clarifying_match.group(0) if clarifying_match else None
    )

    verdict = "fail" if reasons else "pass"

    return {
        "pass": verdict == "pass",
        "verdict": verdict,
        "reasons": reasons,
        "evidence": {
            "premature_tool_calls": premature_tool_calls,
            "decided_response_match": decided_match,
            "clarifying_question_match": clarifying_match_str,
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cmd_assert(turn_file: str) -> None:
    """Load a turn-result JSON file and print the audience-disambiguation finding."""
    path = Path(turn_file)
    if not path.exists():
        _json_err("turn_file_not_found", turn_file)
        return
    try:
        turn_result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _json_err("turn_file_unreadable", str(exc))
        return
    if not isinstance(turn_result, dict):
        _json_err("turn_file_invalid", "top-level JSON must be an object")
        return

    result = check_audience_disambiguation(turn_result)
    _json_out({"turn_file": turn_file, **result})

    if not result["pass"]:
        sys.exit(3)


def _json_out(data: dict[str, Any]) -> None:
    """Write JSON to stdout and exit 0."""
    print(json.dumps(data, ensure_ascii=False, default=str))


def _json_err(error: str, details: str | None = None) -> None:
    """Write error JSON to stderr and exit 1."""
    payload: dict[str, Any] = {"ok": False, "error": error}
    if details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False, default=str), file=sys.stderr)
    sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assert_audience_disambiguation",
        description=(
            "Detect audience-disambiguation violations in a QA turn-1 result. "
            "Fails (exit 3) when the agent prematurely resolves to a gendered "
            "haircut service before the customer stated who the haircut is for."
        ),
    )
    parser.add_argument(
        "--turn-file",
        required=True,
        dest="turn_file",
        help=(
            "Path to a turn-result JSON file produced by "
            "qa_turn_helper.py turn --conversation-id <uuid> ..."
        ),
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _cmd_assert(args.turn_file)


if __name__ == "__main__":
    main()
