"""
Unit tests for booking.md Step 1 — tool-first mandate hardening.

Asserts that the mandatory keywords are present in Step 1 of the booking prompt
after the T-03 fix (greeting-booking-ux-fixes change).
"""

from pathlib import Path


BOOKING_MD = (
    Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "modes" / "booking.md"
)


def _get_step1_text() -> str:
    """Extract Step 1 text from booking.md."""
    content = BOOKING_MD.read_text(encoding="utf-8")
    start = content.find("**1. Servicio**")
    end = content.find("\n\n**2.", start)
    assert start != -1, "Step 1 not found in booking.md"
    return content[start:end] if end != -1 else content[start:]


class TestBookingPromptStep1:
    """T-03 — booking.md Step 1 must contain the tool-first mandate keywords."""

    def test_step1_contains_siempre(self):
        """Step 1 must contain 'SIEMPRE' (tool-first mandate)."""
        step1 = _get_step1_text()
        assert "SIEMPRE" in step1 or "siempre" in step1.lower()

    def test_step1_contains_search_services(self):
        """Step 1 must reference 'search_services' (the tool to call first)."""
        step1 = _get_step1_text()
        assert "search_services" in step1

    def test_step1_contains_nunca(self):
        """Step 1 must contain 'NUNCA' (prohibition on asking before calling tool)."""
        step1 = _get_step1_text()
        assert "NUNCA" in step1 or "nunca" in step1.lower()

    def test_step1_contains_clarification_needed(self):
        """Step 1 must reference 'clarification_needed' (disambiguation path)."""
        step1 = _get_step1_text()
        assert "clarification_needed" in step1

    def test_step1_contains_example(self):
        """Step 1 must contain a concrete example with search_services call."""
        step1 = _get_step1_text()
        # Example must show a user request leading to a search_services call
        assert "cortarme el pelo" in step1 or "corte" in step1
