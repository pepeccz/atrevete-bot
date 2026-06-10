"""TDD tests: T3 — Draft persistence across policy gate.

Covers AS9/AS10 (booking_flow.md Step 5.5 contains round-trip slot list)
and AS11 (R-36 in critical_rules.md cross-references Step 5.5).
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parents[2] / "agent" / "prompts" / "shared"
BOOKING_FLOW = PROMPTS_DIR / "booking_flow.md"
CRITICAL_RULES = PROMPTS_DIR / "critical_rules.md"

# All 9 slot field names that must appear in Step 5.5 per design D3
REQUIRED_SLOT_FIELDS = [
    "services",
    "pre_resolved_service_ids",
    "stylist_name",
    "date_iso",
    "slot_iso",
    "customer_full_name",
    "extras_asked",
    "notes_asked",
    "notes",
]


# ---------------------------------------------------------------------------
# AS9/AS10 — booking_flow.md Step 5.5 contains the full slot list
# ---------------------------------------------------------------------------


def test_booking_flow_step55_contains_slot_list():
    """AS9/AS10: booking_flow.md Step 5.5 must list all 9 required slot fields."""
    content = BOOKING_FLOW.read_text(encoding="utf-8")

    # Locate Step 5.5 section
    step55_pos = content.find("5.5")
    assert step55_pos >= 0, "Step 5.5 not found in booking_flow.md"

    # Find next step or end of file to scope the section
    # Step 5.5 ends at the next top-level step marker (**Paso 6)
    next_step_pos = content.find("**Paso 6", step55_pos)
    step55_text = content[step55_pos:next_step_pos] if next_step_pos > 0 else content[step55_pos:]

    missing = [field for field in REQUIRED_SLOT_FIELDS if field not in step55_text]
    assert not missing, (
        f"booking_flow.md Step 5.5 is missing these required slot field names: {missing}. "
        "These must be listed as the fields to re-pass on update_booking(policy_accepted=True)."
    )


# ---------------------------------------------------------------------------
# AS11 — R-36 cross-references Step 5.5
# ---------------------------------------------------------------------------


def test_r36_cross_references_step55():
    """AS11: R-36 in critical_rules.md must cross-reference Step 5.5 of booking_flow.md."""
    content = CRITICAL_RULES.read_text(encoding="utf-8")

    # Find R-36 block
    r36_pos = content.find("[R36]")
    assert r36_pos >= 0, "R-36 block not found in critical_rules.md"

    # Find R-37 to scope R-36 text
    r37_pos = content.find("[R-37]")
    r36_text = content[r36_pos:r37_pos] if r37_pos > 0 else content[r36_pos:]

    assert "5.5" in r36_text or "Step 5.5" in r36_text or "booking_flow" in r36_text, (
        "R-36 in critical_rules.md must cross-reference Step 5.5 of booking_flow.md. "
        "Add a reference such as 'Ver round-trip completo en booking_flow.md Step 5.5'."
    )
