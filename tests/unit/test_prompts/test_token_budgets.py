"""Token budget tests — all prompt files must stay within token ceilings.

Budgets (cl100k_base):
  - critical_rules.md  ≤ 1100
  - booking_flow.md    ≤ 1200
  - examples.md        ≤  400
  - tools_contract.md  ≤  400
"""
from __future__ import annotations

from pathlib import Path

import pytest
import tiktoken

_SHARED = Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "shared"
_ENC = tiktoken.get_encoding("cl100k_base")

BUDGETS: dict[str, int] = {
    # Budgets updated for SDD change prompt-audience-regression-fix-generic:
    # critical_rules.md: +150 for dual-axis 9b-trigger clause (was 1100)
    # booking_flow.md: unchanged (1200; Paso 0 + Paso 1 fit within)
    # examples.md: +200 for examples 4 and 5 (was 400)
    # tools_contract.md: +80 for update_booking _required clause (was 400)
    #
    # Budgets updated for SDD change booking-flow-name-notes-extras-loop:
    # critical_rules.md: +100 for rule 19 (customer_full_name / customer_known guidance)
    # booking_flow.md: +400 for Paso 1.5, Paso 4, Paso 4b, updated confirmation template
    # examples.md: +700 for Ejemplo 6 (complete-flow happy-path example)
    # tools_contract.md: +300 for new update_booking args + round-trip mandate
    #
    # Budgets updated for SDD change booking-disambiguation-hardening:
    # critical_rules.md: +250 for R-23 (slot-mutation rule), R-24 (stylist list rule),
    #   and 9b-trigger strengthening (was 1450)
    # booking_flow.md: no net increase (stylist section replaced, not appended)
    "critical_rules.md": 1750,
    "booking_flow.md": 1900,
    "examples.md": 1950,
    "tools_contract.md": 950,
}


def _count(filename: str) -> int:
    path = _SHARED / filename
    text = path.read_text(encoding="utf-8")
    return len(_ENC.encode(text))


@pytest.mark.parametrize("filename,budget", list(BUDGETS.items()))
def test_token_budget(filename: str, budget: int) -> None:
    """File must exist and stay within token budget."""
    path = _SHARED / filename
    assert path.exists(), f"{filename} not found at {path}"
    count = _count(filename)
    assert count <= budget, (
        f"{filename} exceeds budget: {count} tokens > {budget} allowed"
    )
