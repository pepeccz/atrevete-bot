"""
CI guard: assert static prompt-consistency invariants over the live prompt
markdown files in `agent/prompts/shared/`.

Mirrors `tests/integration/test_service_catalog_integrity.py`'s shape but is
purely text/regex-based — no DB, no async, runs under normal pytest
discovery.

Invariant covered:
    P1 — R24 (critical_rules.md) and glossary.md agree that "primera con
         disponibilidad" is listed FIRST (position 0).

RESOLVED (qa-loop-conversation-quality, Stream B / B3):
    R24 states "0) payload.first_available_label" (position 0 — the SSOT,
    confirmed by DEC-2) and glossary.md is now reconciled to match (option 0
    is first, before real stylist names). The `xfail` marker from Stream A
    (PR-1) has been removed now that both files agree.

How to run locally:
    pytest tests/integration/test_prompt_consistency_invariants.py -v

How to extend: add a new checker in _prompt_consistency_invariants.py,
register it in CHECKERS, add a description in INVARIANT_DESCRIPTIONS, and
add a corresponding case here + a failure-injection case in
test_prompt_consistency_invariants_failures.py.
"""

from __future__ import annotations

from pathlib import Path

from tests.integration._prompt_consistency_invariants import (
    CHECKERS,
    INVARIANT_DESCRIPTIONS,
    Violation,
)

PROMPTS_DIR = Path(__file__).parent.parent.parent / "agent" / "prompts" / "shared"
CRITICAL_RULES_PATH = PROMPTS_DIR / "critical_rules.md"
GLOSSARY_PATH = PROMPTS_DIR / "glossary.md"


def _format_violations(iid: str, vs: list[Violation]) -> str:
    """Human-readable failure message with a location per violating file."""
    desc = INVARIANT_DESCRIPTIONS[iid]
    lines = [f"{iid} — {desc}", f"  {len(vs)} violation(s):"]
    for v in vs:
        lines.append(f"    • {v.location}: {v.detail}")
    return "\n".join(lines)


def test_p1_first_availability_position_consistent() -> None:
    """P1: critical_rules.md R24 and glossary.md must agree that 'primera con
    disponibilidad' is listed FIRST (position 0).

    GREEN guard — glossary.md was reconciled by Stream B task B3 (see module
    docstring RESOLVED note).
    """
    assert CRITICAL_RULES_PATH.exists(), f"critical_rules.md not found at {CRITICAL_RULES_PATH}"
    assert GLOSSARY_PATH.exists(), f"glossary.md not found at {GLOSSARY_PATH}"

    r24_text = CRITICAL_RULES_PATH.read_text(encoding="utf-8")
    glossary_text = GLOSSARY_PATH.read_text(encoding="utf-8")

    violations = CHECKERS["P1"](r24_text, glossary_text)
    assert not violations, _format_violations("P1", violations)
