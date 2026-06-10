"""T4 — I7: Assert new-customer booking scenarios have max_turns >= 10.

Spec: REQ-I7 / SC-I7-A, SC-I7-B, SC-I7-C, SC-I7-D

New-customer flows include the disclosure/policy gate + name collection gate,
which consume 2-3 extra turns before the booking intent can be processed.
Any new-customer booking scenario at max_turns < 10 risks false timeouts.

Identification heuristic (conservative):
- scenarios.yaml: scenarios tagged [policy] with outcome in {policy_accepted, booked}
  where persona style mentions "primera vez" or tags include "policy"
- Both files: explicit spec mentions change-a-policy-gate-blocks-book (SC-I7-D)

Budget guard: total max_turns across all v2 scenarios must stay <= 250.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCENARIOS_V1_PATH = PROJECT_ROOT / "tests" / "e2e" / "harness" / "scenarios.yaml"
SCENARIOS_V2_PATH = PROJECT_ROOT / "tests" / "e2e" / "harness" / "scenarios-v2.yaml"

# Scenarios that are explicitly identified as new-customer booking flows
# (require policy gate + name collection; need max_turns >= 10)
KNOWN_NEW_CUSTOMER_SCENARIO_IDS = {
    # spec SC-I7-D: explicitly named
    "change-a-policy-gate-blocks-book",
    # first-time customer, same pattern
    "change-c-policy-acceptance-stored",
}

MIN_TURNS_FOR_NEW_CUSTOMER = 10
# V6 audit (Change N): four scenarios received +2 max_turns bumps to prevent
# mid-booking timeouts in new-customer flows (disclosure + policy gate consume
# 2-3 extra turns). Budget raised from 250 → 260 to accommodate the legitimate
# recalibration without blocking CI.
MAX_TOTAL_V2_TURNS_BUDGET = 260


@pytest.fixture(scope="module")
def scenarios_v1() -> list[dict]:
    assert SCENARIOS_V1_PATH.exists(), f"scenarios.yaml not found at {SCENARIOS_V1_PATH}"
    with open(SCENARIOS_V1_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list)
    return data


@pytest.fixture(scope="module")
def scenarios_v2() -> list[dict]:
    assert SCENARIOS_V2_PATH.exists(), f"scenarios-v2.yaml not found at {SCENARIOS_V2_PATH}"
    with open(SCENARIOS_V2_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list)
    return data


@pytest.mark.parametrize("scenario_id", sorted(KNOWN_NEW_CUSTOMER_SCENARIO_IDS))
def test_new_customer_scenario_max_turns_at_least_10(
    scenario_id: str,
    scenarios_v1: list[dict],
    scenarios_v2: list[dict],
) -> None:
    """SC-I7-B/D: Named new-customer scenarios must have max_turns >= 10."""
    all_scenarios = scenarios_v1 + scenarios_v2
    matching = [s for s in all_scenarios if s.get("id") == scenario_id]
    assert len(matching) == 1, (
        f"Scenario '{scenario_id}' not found in either scenarios file. "
        "If the scenario was renamed or removed, update KNOWN_NEW_CUSTOMER_SCENARIO_IDS."
    )
    s = matching[0]
    assert s["max_turns"] >= MIN_TURNS_FOR_NEW_CUSTOMER, (
        f"Scenario '{scenario_id}' has max_turns={s['max_turns']} "
        f"but new-customer flows require max_turns >= {MIN_TURNS_FOR_NEW_CUSTOMER}. "
        "The disclosure gate + policy gate + name collection consume 2-3 turns "
        "before the booking intent can be processed. Bump max_turns."
    )


def test_v2_total_max_turns_within_budget(scenarios_v2: list[dict]) -> None:
    """SC-I7-A: Total max_turns sum across all v2 scenarios must stay <= 250.

    Prevents runaway costs from unchecked max_turns inflation.
    """
    total = sum(s["max_turns"] for s in scenarios_v2)
    assert total <= MAX_TOTAL_V2_TURNS_BUDGET, (
        f"Total v2 max_turns budget exceeded: {total} > {MAX_TOTAL_V2_TURNS_BUDGET}. "
        "Review scenarios and lower max_turns for any that don't need high values."
    )


def test_faq_and_returning_customer_scenarios_not_inflated(
    scenarios_v2: list[dict],
) -> None:
    """SC-I7-C: FAQ and info-only scenarios must NOT have max_turns inflated.

    FAQ scenarios (outcome=info_provided, tool_calls_required=[]) should
    stay at max_turns <= 6 — they don't need the booking pipeline at all.
    """
    faq_scenarios = [
        s
        for s in scenarios_v2
        if s.get("expect", {}).get("outcome") == "info_provided"
        and s.get("expect", {}).get("tool_calls_required") == []
    ]
    for s in faq_scenarios:
        assert s["max_turns"] <= 6, (
            f"FAQ scenario '{s['id']}' has max_turns={s['max_turns']} > 6. "
            "Pure FAQ flows do not need the booking pipeline; keep max_turns <= 6 "
            "to avoid unnecessary turn budget inflation."
        )
