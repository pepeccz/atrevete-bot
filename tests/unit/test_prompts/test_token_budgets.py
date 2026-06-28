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
    #
    # Budgets updated for SDD change booking-ideal-flow-completion:
    # critical_rules.md: +450 for R-22 expansion + new R-26/R-27 closed_day + advance_policy (was 1750)
    # booking_flow.md: +800 for Paso 2 slot-first rewrite, offer_slots/closed_day/advance handlers,
    #   notes personalisation with stylist name (was 1900)
    # examples.md: +650 for Ejemplo 8 slot-first happy path (was 1950)
    # tools_contract.md: +400 for offer_slots routing table + closed_day/advance_policy entries (was 950)
    # Budgets updated for SDD change availability-context-injection-and-grounding:
    # critical_rules.md: +200 for R-28 (dia_semana from <today>) + R-29 (no-hallucinated-slots)
    # booking_flow.md: +350 for <availability> block primary source section
    # tools_contract.md: +400 for slot_time param description + pre-book gate mandate
    # Budgets updated for SDD change v6-fixes-bundle (Change N):
    # critical_rules.md: was already over budget at baseline (3359 > 2400 — budget
    #   was stale, not bumped by previous changes). Re-baselined to actual (3359)
    #   + ~150 for the R-37 negative scope (illness as cancellation reason, N4).
    # tools_contract.md: also stale at baseline (1772 > 1750). Re-baselined to
    #   actual + ~180 for the escalate failure contract (N2) and the
    #   escalation_required routing row (N3).
    # booking_flow.md: +250 for the Paso 2 qualifier→audience mapping (N5),
    #   fits within the existing 3050 budget.
    # critical_rules.md: +200 for R-42 (tool-backed confirmation rule — blocks
    #   hallucinated booking confirmations; see PR #77). Actual 3708.
    # tools_contract.md: +50 for `services` field note (UUIDs-in-services defence; see
    #   uuid-reroute fix). Actual 2070 → bumped to 2100.
    # critical_rules.md: 3800 → 4100 for R-43 (service-suggestion no-escalate) +
    #   R-44 (multi-person sequential flows) from multi-service PR-2 (#87). Detail
    #   lives in booking_flow.md; the R-NN rules here are the terse statements.
    #   Reconciles the duplicate budget in test_critical_rules_content.py. Actual 4010.
    "critical_rules.md": 4100,
    "booking_flow.md": 3050,
    "examples.md": 2600,
    "tools_contract.md": 2100,
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
    assert count <= budget, f"{filename} exceeds budget: {count} tokens > {budget} allowed"
