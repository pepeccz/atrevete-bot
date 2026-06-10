"""TDD tests: T2 — Allergy safety gate (prompt content).

Covers AS1/AS2/AS3 (R-37 in critical_rules.md) and AS4 (Example 6 rewrite in examples.md).
Also covers E1 (gate applies even after policy acceptance).
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parents[2] / "agent" / "prompts" / "shared"
CRITICAL_RULES = PROMPTS_DIR / "critical_rules.md"
EXAMPLES = PROMPTS_DIR / "examples.md"
BOOKING_FLOW = PROMPTS_DIR / "booking_flow.md"


# ---------------------------------------------------------------------------
# AS3 — R-37 present in critical_rules.md
# ---------------------------------------------------------------------------


def test_r37_rule_exists():
    """AS3: critical_rules.md must contain R-37 with medical_consultation and chemical dimension."""
    content = CRITICAL_RULES.read_text(encoding="utf-8")
    assert "R-37" in content or "R37" in content, "R-37 rule not found in critical_rules.md"
    assert "medical_consultation" in content, (
        "R-37 must reference 'medical_consultation' escalation reason"
    )
    # Must mention at least some chemical service
    assert any(
        svc in content for svc in ["tinte", "mechas", "decoloración", "alisado"]
    ), "R-37 must list chemical service types"


def test_r37_trigger_set_complete():
    """AS3: R-37 trigger set must contain the canonical phrases."""
    content = CRITICAL_RULES.read_text(encoding="utf-8").lower()
    required_triggers = ["alergia", "embaraz", "medicaci"]
    for trigger in required_triggers:
        assert trigger in content, (
            f"R-37 trigger set missing phrase containing '{trigger}'. "
            f"Check critical_rules.md R-37."
        )


# ---------------------------------------------------------------------------
# AS4 — Example 6 shows escalate path, not book
# ---------------------------------------------------------------------------


def test_example6_shows_escalate_not_book():
    """AS4: Example 6 must show escalate(reason='medical_consultation'), not book, after allergy."""
    content = EXAMPLES.read_text(encoding="utf-8")

    # Locate Example 6 section
    example6_start = content.find("### Ejemplo 6")
    assert example6_start >= 0, "Example 6 section not found in examples.md"

    # Find next example section to scope the search
    next_example = content.find("### Ejemplo", example6_start + 1)
    example6_text = content[example6_start:next_example] if next_example > 0 else content[example6_start:]

    # Must contain escalate call
    assert "escalate" in example6_text, (
        "Example 6 must demonstrate 'escalate' call for allergy trigger, not book"
    )
    # Must contain medical_consultation reason
    assert "medical_consultation" in example6_text, (
        "Example 6 must use escalate(reason='medical_consultation')"
    )
    # Must NOT show book( after the allergy trigger (allergy path must not book)
    # Find position of allergy trigger in example 6
    alergia_pos = example6_text.lower().find("alergia")
    if alergia_pos >= 0:
        text_after_alergia = example6_text[alergia_pos:]
        # After the allergy mention, escalate must appear before any book( call
        escalate_pos = text_after_alergia.find("escalate")
        book_pos = text_after_alergia.find("book(")
        if book_pos >= 0:
            assert escalate_pos < book_pos, (
                "In Example 6 allergy path: escalate must appear before book(, or book must be absent"
            )


# ---------------------------------------------------------------------------
# AS1 — booking_flow.md Step 5.0 safety gate present BEFORE 5.5
# ---------------------------------------------------------------------------


def test_booking_flow_step50_present():
    """AS1/E1: booking_flow.md must have a Step 5.0 safety gate section before Step 5.5."""
    content = BOOKING_FLOW.read_text(encoding="utf-8")

    # Step 5.0 must exist
    assert "5.0" in content or "Paso 5.0" in content or "Step 5.0" in content, (
        "booking_flow.md must contain a Step 5.0 (safety gate) section"
    )

    # Must mention the safety concept
    step50_pos = content.lower().find("5.0")
    step55_pos = content.lower().find("5.5")

    assert step50_pos >= 0, "Step 5.0 not found in booking_flow.md"
    assert step55_pos >= 0, "Step 5.5 not found in booking_flow.md (reference lost?)"
    assert step50_pos < step55_pos, (
        "Step 5.0 must appear BEFORE Step 5.5 in booking_flow.md"
    )
