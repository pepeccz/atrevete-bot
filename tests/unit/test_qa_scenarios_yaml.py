"""Unit tests for scenarios.yaml schema validation (AS9).

Covers:
- YAML file exists and parses without error
- At least 15 scenarios present
- Each scenario has required fields: id, persona, intent, max_turns, expect
- All ids are unique
- All phones start with +34999 (TEST_PHONE_PREFIX default)
- max_turns <= 12 for all scenarios
- expect.outcome is from the valid enum
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCENARIOS_PATH = Path(__file__).parent.parent.parent / "tests" / "e2e" / "harness" / "scenarios.yaml"

VALID_OUTCOMES = {
    "booked",
    "cancelled",
    "rescheduled",
    "escalated",
    "policy_accepted",
    "timeout",
    "error",
    "rejected",
}

TEST_PHONE_PREFIX = "+34999"


@pytest.fixture(scope="module")
def scenarios() -> list[dict]:
    """Load and return scenarios from YAML file."""
    assert SCENARIOS_PATH.exists(), f"scenarios.yaml not found at {SCENARIOS_PATH}"
    with open(SCENARIOS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, list), "scenarios.yaml must be a YAML list"
    return data


def test_scenarios_yaml_exists() -> None:
    """AS9: scenarios.yaml file exists."""
    assert SCENARIOS_PATH.exists(), f"scenarios.yaml not found at {SCENARIOS_PATH}"


def test_scenarios_yaml_parses_without_error() -> None:
    """AS9: scenarios.yaml parses without YAML errors."""
    with open(SCENARIOS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data is not None


def test_scenarios_count_at_least_15(scenarios: list[dict]) -> None:
    """AS9: At least 15 scenarios present."""
    assert len(scenarios) >= 15, f"Expected >= 15 scenarios, got {len(scenarios)}"


def test_scenarios_have_required_fields(scenarios: list[dict]) -> None:
    """AS9: Every scenario has id, persona, intent, max_turns, expect."""
    required_top_level = {"id", "persona", "intent", "max_turns", "expect"}
    required_persona = {"name", "phone"}
    required_expect = {"outcome"}

    for i, scenario in enumerate(scenarios):
        missing = required_top_level - set(scenario.keys())
        assert not missing, f"Scenario [{i}] missing top-level fields: {missing}"

        persona = scenario["persona"]
        missing_persona = required_persona - set(persona.keys())
        assert not missing_persona, f"Scenario [{i}] persona missing fields: {missing_persona}"

        expect = scenario["expect"]
        missing_expect = required_expect - set(expect.keys())
        assert not missing_expect, f"Scenario [{i}] expect missing fields: {missing_expect}"


def test_scenario_ids_are_unique(scenarios: list[dict]) -> None:
    """AS9: All scenario ids are unique."""
    ids = [s["id"] for s in scenarios]
    assert len(ids) == len(set(ids)), f"Duplicate scenario ids found: {[x for x in ids if ids.count(x) > 1]}"


def test_all_phones_start_with_test_prefix(scenarios: list[dict]) -> None:
    """AS9: All persona phones start with TEST_PHONE_PREFIX (+34999)."""
    for scenario in scenarios:
        phone = scenario["persona"]["phone"]
        assert phone.startswith(TEST_PHONE_PREFIX), (
            f"Scenario '{scenario['id']}' has phone '{phone}' that doesn't start with '{TEST_PHONE_PREFIX}'"
        )


def test_max_turns_within_limit(scenarios: list[dict]) -> None:
    """AS9: max_turns <= 12 for all scenarios."""
    for scenario in scenarios:
        max_turns = scenario["max_turns"]
        assert isinstance(max_turns, int), f"Scenario '{scenario['id']}' max_turns must be int"
        assert max_turns <= 12, (
            f"Scenario '{scenario['id']}' has max_turns={max_turns}, max allowed is 12"
        )


def test_expect_outcome_is_valid_enum(scenarios: list[dict]) -> None:
    """AS9: expect.outcome is from the valid enum."""
    for scenario in scenarios:
        outcome = scenario["expect"]["outcome"]
        assert outcome in VALID_OUTCOMES, (
            f"Scenario '{scenario['id']}' has invalid outcome '{outcome}'. "
            f"Valid values: {sorted(VALID_OUTCOMES)}"
        )


def test_scenario_ids_follow_naming_convention(scenarios: list[dict]) -> None:
    """AS9: Scenario ids follow change-X-description convention."""
    for scenario in scenarios:
        sid = scenario["id"]
        assert "-" in sid, f"Scenario id '{sid}' should be kebab-case with dashes"
        assert sid == sid.lower(), f"Scenario id '{sid}' should be lowercase"


def test_phones_are_unique(scenarios: list[dict]) -> None:
    """AS9: Each scenario uses a distinct phone number."""
    phones = [s["persona"]["phone"] for s in scenarios]
    assert len(phones) == len(set(phones)), (
        f"Duplicate phones found: {[p for p in phones if phones.count(p) > 1]}"
    )
