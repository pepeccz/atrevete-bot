"""T-9 — RED tests for prompt content assertions (category mix rules).

Tests that:
- critical_rules.md contains R-25 rule
- booking_flow.md contains "category_mix_required" and "Paso 1.5"
- tools_contract.md enumerates "category_mix_required" under update_booking
"""
from __future__ import annotations

from pathlib import Path

PROMPTS_SHARED = Path(__file__).parents[2] / "agent" / "prompts" / "shared"


def _read(filename: str) -> str:
    return (PROMPTS_SHARED / filename).read_text(encoding="utf-8")


def test_critical_rules_contains_r25_category_rule():
    """critical_rules.md must contain rule R-25 about category restriction."""
    content = _read("critical_rules.md")
    import re

    # Accept both "[R25]" (current bracket format) and legacy "25." prefix format
    has_r25 = bool(re.search(r"^\[R25\]|^25\.", content, re.MULTILINE))
    assert has_r25, (
        "critical_rules.md must contain rule R-25 about one-category-per-appointment"
    )


def test_booking_flow_contains_category_mix_required_step():
    """booking_flow.md must contain a category-mix step and category_mix_required."""
    content = _read("booking_flow.md")
    assert "category_mix_required" in content, (
        "booking_flow.md must document the category_mix_required next_step"
    )
    # Accept "Paso 1.5", "Paso 2.5", or any "Paso N.5" variant for the category-mix step
    import re

    has_category_paso = bool(re.search(r"Paso \d+\.5", content))
    assert has_category_paso, (
        "booking_flow.md must contain a Paso N.5 section about category mix"
    )


def test_tools_contract_enumerates_category_mix_required():
    """tools_contract.md must enumerate category_mix_required under update_booking."""
    content = _read("tools_contract.md")
    assert "category_mix_required" in content, (
        "tools_contract.md must list category_mix_required as a valid next_step for update_booking"
    )
