"""Regression guard for hallucinated booking confirmations (F1).

A PURE, importable + CLI-runnable helper that detects the "unbacked confirmation"
class of bug: the bot (Maite) tells the customer a booking / cancellation / reschedule
is confirmed WITHOUT a real appointment ever being persisted.

The DB existence check (`appointment_exists`) is supplied EXTERNALLY by the reconciler
since DB access is out-of-band. This keeps the helper pure and unit-testable.

Usage:
    # As a library
    from tests.e2e.harness.assert_claim_backend import detect_unbacked_confirmation
    finding = detect_unbacked_confirmation(agent_messages, appointment_exists=False)

    # As a CLI
    python tests/e2e/harness/assert_claim_backend.py \
        --run-file tests/e2e/runs/<ts>/<scenario_id>.json \
        --appointment-exists false
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# BOOKING confirmation phrasing regex.
#
# This helper is BOOKING-scoped: it flags hallucinated NEW-booking confirmations. The
# pattern tuple MUST stay byte-for-byte identical to
# agent/middleware/response_groundedness.py::_BOOKING_CONFIRMATION_PATTERNS. It is
# duplicated here on purpose so the harness has no import-time dependency on the agent
# package (and so the regression guard keeps working even if the middleware is
# refactored). A drift-guard unit test
# (tests/unit/test_response_groundedness_middleware.py) imports both module-level
# tuples and asserts equality, so editing one without the other fails CI.
#
# Cancel/reschedule (mutation) confirmations are intentionally NOT covered here
# (BLOCKER-1: manage_appointments returns a plain string, so success cannot be
# verified; gating those would false-positive on legitimate cancellations).
# ---------------------------------------------------------------------------
_BOOKING_CONFIRMATION_PATTERNS: tuple[str, ...] = (
    r"te\s+(he\s+|queda\s+)?(confirmad|reservad|agendad)\w*",
    r"reserva\s+confirmada",
    r"cita\s+(?:\w+\s+){0,3}(confirmada|reservada|agendada)",
    r"^\s*¡?listo!?\b.*cit",
    r"ya\s+est[áa]\s+tu\s+cita",
    r"tu\s+cita\s+queda",
    r"quedas\s+anotad\w*",
    r"cita\s+(?:\w+\s+){0,3}agendada",
    r"¡?hecho!?(?:\W+\w+){0,4}\W+(?:cita|reserva)",
    r"(?:cita|reserva)(?:\W+\w+){0,4}\W+¡?hecho!?",
)

# Backwards-compatible alias (kept so existing importers keep working).
_CONFIRMATION_PATTERNS: tuple[str, ...] = _BOOKING_CONFIRMATION_PATTERNS

_CONFIRMATION_RE = re.compile(
    "|".join(f"(?:{p})" for p in _BOOKING_CONFIRMATION_PATTERNS),
    re.IGNORECASE | re.MULTILINE,
)


def detect_unbacked_confirmation(
    agent_messages: list[str],
    appointment_exists: bool,
) -> dict[str, Any]:
    """Detect a hallucinated (unbacked) booking confirmation.

    Pure function: given the agent's reply texts and whether a real appointment exists
    in the DB, flag the case where any reply asserts a confirmation but no appointment
    was persisted.

    Args:
        agent_messages: The agent's reply texts for each turn of a scenario.
        appointment_exists: Whether a real appointment exists in the DB (supplied by
            the reconciler — DB access is out-of-band).

    Returns:
        {
          "hallucinated_confirmation": bool,
          "matched_phrase": str | None,
        }
    """
    matched_phrase: str | None = None
    for message in agent_messages or []:
        if not isinstance(message, str) or not message:
            continue
        match = _CONFIRMATION_RE.search(message)
        if match:
            matched_phrase = match.group(0)
            break

    hallucinated = matched_phrase is not None and not appointment_exists
    return {
        "hallucinated_confirmation": hallucinated,
        "matched_phrase": matched_phrase if hallucinated else None,
    }


def _extract_agent_messages(run: dict[str, Any]) -> list[str]:
    """Extract the agent_response of each turn from a run JSON dict.

    Tolerates partial/malformed run dicts: missing `turns` and null `agent_response`
    values are skipped, never raised on.
    """
    messages: list[str] = []
    for turn in run.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        response = turn.get("agent_response")
        if isinstance(response, str) and response:
            messages.append(response)
    return messages


def _cmd_assert(run_file: str, appointment_exists: bool) -> None:
    """Load a run JSON file and print the unbacked-confirmation finding."""
    path = Path(run_file)
    if not path.exists():
        _json_err("run_file_not_found", run_file)
        return
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _json_err("run_file_unreadable", str(exc))
        return

    finding = detect_unbacked_confirmation(
        _extract_agent_messages(run),
        appointment_exists=appointment_exists,
    )
    _json_out(
        {
            "scenario_id": run.get("scenario_id"),
            "appointment_exists": appointment_exists,
            **finding,
        }
    )


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


def _str_to_bool(value: str) -> bool:
    """Parse a CLI true/false string into a bool."""
    return value.strip().lower() in {"true", "1", "yes", "y"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assert_claim_backend",
        description="Detect hallucinated (unbacked) booking confirmations in a run.",
    )
    parser.add_argument(
        "--run-file",
        required=True,
        dest="run_file",
        help="Path to {scenario_id}.json run file",
    )
    parser.add_argument(
        "--appointment-exists",
        required=True,
        dest="appointment_exists",
        help="Whether a real appointment exists in the DB (true|false)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _cmd_assert(args.run_file, _str_to_bool(args.appointment_exists))


if __name__ == "__main__":
    main()
