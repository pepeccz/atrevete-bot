"""
CI guard: assert static prompt-consistency invariants over the live prompt
markdown files in `agent/prompts/shared/`.

Mirrors `tests/integration/test_service_catalog_integrity.py`'s shape but is
purely text/regex-based — no DB, no async, runs under normal pytest
discovery.

Invariant covered:
    P1 — R24 (critical_rules.md) and glossary.md agree that "primera con
         disponibilidad" is listed FIRST (position 0).

XFAIL NOTE (qa-loop-conversation-quality, Stream A / PR-1):
    As of this PR, R24 already states "0) payload.first_available_label"
    (position 0 — the SSOT, confirmed by DEC-2), but glossary.md has NOT yet
    been reconciled (it still says the option goes "al final"). This is a
    KNOWN, INTENTIONAL divergence — Stream B task B3 reconciles glossary.md
    to match R24. Until B3 lands, this test is expected to FAIL; it is marked
    `xfail(strict=False)` so CI stays green on master while still exercising
    the checker against live files. The failure-injection tests in
    test_prompt_consistency_invariants_failures.py already prove the checker
    correctly detects this exact divergence pattern using synthetic text.
    Remove the xfail marker in B3 once glossary.md is reconciled.

How to run locally:
    pytest tests/integration/test_prompt_consistency_invariants.py -v

How to extend: add a new checker in _prompt_consistency_invariants.py,
register it in CHECKERS, add a description in INVARIANT_DESCRIPTIONS, and
add a corresponding case here + a failure-injection case in
test_prompt_consistency_invariants_failures.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


@pytest.mark.xfail(
    reason="known R24/glossary divergence — resolved by qa-loop B3",
    strict=False,
)
def test_p1_first_availability_position_consistent() -> None:
    """P1: critical_rules.md R24 and glossary.md must agree that 'primera con
    disponibilidad' is listed FIRST (position 0).

    Expected to FAIL until Stream B task B3 reconciles glossary.md (see module
    docstring XFAIL NOTE). Not CI-blocking while xfail(strict=False).
    """
    assert CRITICAL_RULES_PATH.exists(), f"critical_rules.md not found at {CRITICAL_RULES_PATH}"
    assert GLOSSARY_PATH.exists(), f"glossary.md not found at {GLOSSARY_PATH}"

    r24_text = CRITICAL_RULES_PATH.read_text(encoding="utf-8")
    glossary_text = GLOSSARY_PATH.read_text(encoding="utf-8")

    violations = CHECKERS["P1"](r24_text, glossary_text)
    assert not violations, _format_violations("P1", violations)
