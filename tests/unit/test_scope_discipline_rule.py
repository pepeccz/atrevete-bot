"""TDD tests: T6 — Scope discipline rule R-38.

Covers AS18 (R-38 present in critical_rules.md with booking deflection constraint)
and validates identity.md cross-references R-38.
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parents[2] / "agent" / "prompts" / "shared"
IDENTITY = PROMPTS_DIR / "identity.md"
CRITICAL_RULES = PROMPTS_DIR / "critical_rules.md"


# ---------------------------------------------------------------------------
# AS18 — R-38 present in critical_rules.md
# ---------------------------------------------------------------------------


def test_r38_rule_exists():
    """AS18: critical_rules.md must contain R-38."""
    content = CRITICAL_RULES.read_text(encoding="utf-8")
    assert "R-38" in content or "R38" in content, (
        "R-38 rule not found in critical_rules.md. "
        "This rule must define the booking-only scope discipline."
    )


def test_r38_contains_booking_deflection_constraint():
    """AS18: R-38 must mention 1-2 sentence deflection rule."""
    content = CRITICAL_RULES.read_text(encoding="utf-8")

    r38_pos = content.find("R-38")
    if r38_pos < 0:
        r38_pos = content.find("R38")
    assert r38_pos >= 0, "R-38 not found"

    # Take up to 500 chars after R-38 to read the rule text
    r38_text = content[r38_pos: r38_pos + 500]

    assert "1-2" in r38_text or "una o dos" in r38_text or "1 o 2" in r38_text, (
        f"R-38 must specify '1-2' sentence deflection limit. "
        f"R-38 text excerpt: {r38_text!r}"
    )


# ---------------------------------------------------------------------------
# identity.md cross-references R-38
# ---------------------------------------------------------------------------


def test_identity_references_r38():
    """AS18: identity.md must cross-reference R-38."""
    if not IDENTITY.exists():
        raise AssertionError(f"identity.md not found at {IDENTITY}")
    content = IDENTITY.read_text(encoding="utf-8")
    assert "R-38" in content or "R38" in content, (
        "identity.md must cross-reference R-38 (scope discipline rule). "
        "Add a one-line reminder such as 'Soy asistente de reservas únicamente — ver R-38.'"
    )
