"""
Prompt-consistency invariant checks — pure text/regex helpers.

Mirrors `tests/integration/_service_catalog_invariants.py`: each checker takes
TEXT inputs (not file paths) so the same function powers both the green
file-based test (reads live `critical_rules.md`/`glossary.md`) and a synthetic
red-injection test (feeds crafted divergent strings). No DB, no async — plain
regex over prompt markdown.

P1 — R24 (critical_rules.md) vs glossary.md "primera con disponibilidad"
list-position claim. Per DEC-2 (qa-loop-conversation-quality): option 0
(first) is the confirmed direction — R24 already states this; glossary.md
is reconciled by Stream B task B3.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Violation dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """A single prompt-consistency invariant violation."""

    invariant_id: str
    location: str
    detail: str


# ---------------------------------------------------------------------------
# Invariant descriptions (used for failure message headers)
# ---------------------------------------------------------------------------

INVARIANT_DESCRIPTIONS: dict[str, str] = {
    "P1": (
        "R24 (critical_rules.md) and glossary.md must agree that 'primera con "
        "disponibilidad' is listed FIRST (position 0)"
    ),
}

# ---------------------------------------------------------------------------
# P1 — first-availability list-position agreement
# ---------------------------------------------------------------------------

# R24 SSOT pattern: `0)` `payload.first_available_label` at position 0 (first).
# Tolerates markdown code-span punctuation/backticks/whitespace between "0)"
# and the label (e.g. "`0)` `payload.first_available_label`").
_R24_FIRST_POSITION_RE = re.compile(
    r"0\)[^a-zA-Z0-9]{0,10}payload\.first_available_label", re.IGNORECASE
)

# glossary.md divergence pattern: explicitly states the option goes LAST.
_GLOSSARY_SAYS_LAST_RE = re.compile(
    r"primera con disponibilidad.{0,40}(al final|\bultim)",
    re.IGNORECASE | re.DOTALL,
)


def check_first_availability_position(r24_text: str, glossary_text: str) -> list[Violation]:
    """P1: R24 and glossary.md must agree that 'primera con disponibilidad' is
    listed FIRST (position 0), per R24 (SSOT) and DEC-2 (option 0 wins).

    Divergence detected when:
      - R24 does not place `first_available_label` at position 0 (SSOT drift), OR
      - glossary.md still states the option goes "al final" / "último"
        (unreconciled — the historical divergence this invariant guards against).

    Pure text/regex — no I/O. Case-insensitive.
    """
    violations: list[Violation] = []

    if not _R24_FIRST_POSITION_RE.search(r24_text):
        violations.append(
            Violation(
                invariant_id="P1",
                location="critical_rules.md R24",
                detail=(
                    "R24 does not place `0) payload.first_available_label` at position 0 "
                    "(expected SSOT: option 0 is first)"
                ),
            )
        )

    if _GLOSSARY_SAYS_LAST_RE.search(glossary_text):
        violations.append(
            Violation(
                invariant_id="P1",
                location="glossary.md",
                detail=(
                    "glossary.md still states 'primera con disponibilidad' goes "
                    "'al final'/'último', diverging from R24 (option 0 is first)"
                ),
            )
        )

    return violations


# ---------------------------------------------------------------------------
# CHECKERS registry — maps invariant ID -> checker function
# ---------------------------------------------------------------------------
#
# Extensibility: add `_check_prompt_invariant_2` (or another descriptively
# named checker) above, register it here with a new ID, and add a matching
# entry to INVARIANT_DESCRIPTIONS. E.g. a future invariant could assert
# policy-message wording parity between booking_flow.md Paso 5.5 and R36.

CHECKERS: dict[str, Callable[..., object]] = {
    "P1": check_first_availability_position,
}
