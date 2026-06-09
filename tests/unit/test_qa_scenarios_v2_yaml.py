"""Unit tests for scenarios-v2.yaml schema validation (expansion battery).

Mirrors test_qa_scenarios_yaml.py but for the v2 expansion file (25 scenarios
covering realistic salon conversation distribution beyond the regression core).

Validates:
- File exists and parses
- >= 20 scenarios present
- Required fields per scenario
- Unique ids and phones
- All phones start with +34999
- max_turns <= 14 (relaxed from v1's 12 for multi-intent complexity)
- expect.outcome in extended enum (includes info_provided, multi_completed,
  partial_completed, out_of_scope_handled, stuck)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCENARIOS_V2_PATH = (
    Path(__file__).parent.parent.parent
    / "tests"
    / "e2e"
    / "harness"
    / "scenarios-v2.yaml"
)

VALID_OUTCOMES_V2 = {
    # v1 outcomes
    "booked",
    "cancelled",
    "rescheduled",
    "escalated",
    "policy_accepted",
    "timeout",
    "error",
    "rejected",
    # v2 additions for FAQ / multi-intent / out-of-scope / edge
    "info_provided",
    "multi_completed",
    "partial_completed",
    "out_of_scope_handled",
    "stuck",
}

TEST_PHONE_PREFIX = "+34999"
MAX_TURNS_CAP_V2 = 14


@pytest.fixture(scope="module")
def scenarios_v2() -> list[dict]:
    assert SCENARIOS_V2_PATH.exists(), f"scenarios-v2.yaml not found at {SCENARIOS_V2_PATH}"
    with open(SCENARIOS_V2_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list), "scenarios-v2.yaml must be a YAML list"
    return data


def test_v2_file_exists() -> None:
    assert SCENARIOS_V2_PATH.exists()


def test_v2_parses_without_error() -> None:
    with open(SCENARIOS_V2_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data is not None


def test_v2_count_at_least_20(scenarios_v2: list[dict]) -> None:
    assert len(scenarios_v2) >= 20, f"Expected >= 20 scenarios, got {len(scenarios_v2)}"


def test_v2_required_fields(scenarios_v2: list[dict]) -> None:
    required = {"id", "persona", "intent", "max_turns", "expect"}
    for scenario in scenarios_v2:
        missing = required - scenario.keys()
        assert not missing, f"Scenario '{scenario.get('id', '?')}' missing: {missing}"


def test_v2_ids_unique(scenarios_v2: list[dict]) -> None:
    ids = [s["id"] for s in scenarios_v2]
    assert len(ids) == len(set(ids)), "Duplicate scenario ids found"


def test_v2_phones_unique(scenarios_v2: list[dict]) -> None:
    phones = [s["persona"]["phone"] for s in scenarios_v2]
    assert len(phones) == len(set(phones)), "Duplicate phones found"


def test_v2_phones_use_test_prefix(scenarios_v2: list[dict]) -> None:
    for scenario in scenarios_v2:
        phone = scenario["persona"]["phone"]
        assert phone.startswith(TEST_PHONE_PREFIX), (
            f"Scenario '{scenario['id']}' phone {phone!r} does not start with "
            f"{TEST_PHONE_PREFIX!r}"
        )


def test_v2_max_turns_within_cap(scenarios_v2: list[dict]) -> None:
    for scenario in scenarios_v2:
        turns = scenario["max_turns"]
        assert 1 <= turns <= MAX_TURNS_CAP_V2, (
            f"Scenario '{scenario['id']}' max_turns={turns} outside [1, {MAX_TURNS_CAP_V2}]"
        )


def test_v2_outcome_in_valid_enum(scenarios_v2: list[dict]) -> None:
    for scenario in scenarios_v2:
        outcome = scenario["expect"]["outcome"]
        assert outcome in VALID_OUTCOMES_V2, (
            f"Scenario '{scenario['id']}' has invalid outcome '{outcome}'. "
            f"Valid v2: {sorted(VALID_OUTCOMES_V2)}"
        )


def test_v2_persona_has_required_fields(scenarios_v2: list[dict]) -> None:
    for scenario in scenarios_v2:
        persona = scenario["persona"]
        for field in ("name", "phone", "style"):
            assert field in persona, f"Scenario '{scenario['id']}' persona missing {field}"


def test_v2_expect_has_required_fields(scenarios_v2: list[dict]) -> None:
    for scenario in scenarios_v2:
        expect = scenario["expect"]
        assert "outcome" in expect, f"Scenario '{scenario['id']}' expect missing outcome"
        # tool_calls_required/forbidden may be empty lists
        for field in ("tool_calls_required", "tool_calls_forbidden"):
            assert field in expect, f"Scenario '{scenario['id']}' expect missing {field}"
            assert isinstance(expect[field], list), (
                f"Scenario '{scenario['id']}' expect.{field} must be a list"
            )
