"""T-9 — RED tests for prompt content assertions (category mix rules).

Tests that:
- critical_rules.md contains R-25 rule
- booking_flow.md contains "category_mix_required" and "Paso 1.5"
- tools_contract.md enumerates "category_mix_required" under update_booking
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROMPTS_SHARED = Path(__file__).parents[2] / "agent" / "prompts" / "shared"


def _read(filename: str) -> str:
    return (PROMPTS_SHARED / filename).read_text(encoding="utf-8")


def test_critical_rules_contains_r25_category_rule():
    """critical_rules.md must contain rule R-25 about category restriction."""
    content = _read("critical_rules.md")
    # Expect a line starting with 25. followed by something about category
    import re

    has_r25 = bool(re.search(r"^25\.", content, re.MULTILINE))
    assert has_r25, (
        "critical_rules.md must contain rule 25. (R-25) about one-category-per-appointment"
    )


def test_booking_flow_contains_category_mix_required_step():
    """booking_flow.md must contain Paso 1.5 and category_mix_required."""
    content = _read("booking_flow.md")
    assert "category_mix_required" in content, (
        "booking_flow.md must document the category_mix_required next_step"
    )
    assert "Paso 1.5" in content or "1.5" in content, (
        "booking_flow.md must contain Paso 1.5 section about category mix"
    )


def test_tools_contract_enumerates_category_mix_required():
    """tools_contract.md must enumerate category_mix_required under update_booking."""
    content = _read("tools_contract.md")
    assert "category_mix_required" in content, (
        "tools_contract.md must list category_mix_required as a valid next_step for update_booking"
    )
