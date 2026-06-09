"""TDD tests: T4 — Mark availability XML as orientative.

Covers AS12 (booking_flow.md Steps 5-6 mark availability as orientative)
and AS13 (_format_availability_xml footer contains orientative marker).
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parents[2] / "agent" / "prompts" / "shared"
BOOKING_FLOW = PROMPTS_DIR / "booking_flow.md"


# ---------------------------------------------------------------------------
# AS13 — XML footer contains orientative marker
# ---------------------------------------------------------------------------


def test_xml_footer_contains_orientative_marker():
    """AS13: _format_availability_xml output must contain 'orientativ' and 'check_availability' in footer."""
    from agent.middleware.availability_context import _format_availability_xml

    # Minimal sample window matching the expected data structure
    sample_window = {
        "Marta": [
            {
                "date_iso": "2026-06-15",
                "weekday_es": "lunes",
                "slots": ["10:00", "11:00"],
            }
        ]
    }

    output = _format_availability_xml(sample_window)

    assert "orientativ" in output.lower(), (
        "Availability XML footer must contain 'orientativ' (stem for orientativo/orientativa). "
        f"Got footer section: {output[-200:]!r}"
    )
    assert "check_availability" in output, (
        "Availability XML footer must mention 'check_availability' as the required revalidation tool. "
        f"Got footer section: {output[-200:]!r}"
    )
    # Footer must appear before closing tag
    closing_tag_pos = output.rfind("</availability>")
    footer_pos = output.lower().rfind("orientativ")
    assert footer_pos < closing_tag_pos, (
        "Orientative marker must appear BEFORE </availability> closing tag"
    )


# ---------------------------------------------------------------------------
# AS12 — booking_flow.md Steps 5-6 mark availability as orientative
# ---------------------------------------------------------------------------


def test_booking_flow_steps_56_mark_orientative():
    """AS12: booking_flow.md must state availability block is orientative and check_availability is mandatory."""
    content = BOOKING_FLOW.read_text(encoding="utf-8")

    # Check for orientative language in the availability block section
    assert "orientativ" in content.lower(), (
        "booking_flow.md must describe <availability> block as orientative (orientativo/orientativa)"
    )
    # Must mention check_availability as mandatory before proposing a slot
    assert "check_availability" in content, (
        "booking_flow.md must state that check_availability is mandatory before proposing a concrete slot"
    )
