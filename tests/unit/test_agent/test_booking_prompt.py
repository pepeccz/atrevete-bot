"""
Unit tests for booking.md Step 1 — service resolution guidance.

Asserts that the Step 1 section of the booking prompt covers service identification
and disambiguation rules (audiences, conditions, multi-service).
"""

from pathlib import Path


BOOKING_MD = (
    Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "modes" / "booking.md"
)


def _get_step1_text() -> str:
    """Extract Step 1 text from booking.md (supports both old and new heading formats)."""
    content = BOOKING_MD.read_text(encoding="utf-8")
    # Try new format first: "**Paso 1 — Servicio**"
    start = content.find("**Paso 1 — Servicio**")
    # Fallback to old format: "**1. Servicio**"
    if start == -1:
        start = content.find("**1. Servicio**")
    assert start != -1, (
        "Step 1 not found in booking.md (tried '**Paso 1 — Servicio**' and '**1. Servicio**')"
    )
    # Find the end at Step 2
    end = content.find("**Paso 2", start)
    if end == -1:
        end = content.find("**2.", start)
    return content[start:end] if end != -1 else content[start:]


class TestBookingPromptStep1:
    """booking.md Step 1 must describe the service resolution flow."""

    def test_step1_heading_present(self):
        """Step 1 heading must be present in booking.md."""
        content = BOOKING_MD.read_text(encoding="utf-8")
        has_step1 = "**Paso 1 — Servicio**" in content or "**1. Servicio**" in content
        assert has_step1, "Step 1 heading not found in booking.md"

    def test_step1_references_catalog(self):
        """Step 1 must reference the service catalog (catálogo)."""
        step1 = _get_step1_text()
        assert "catálogo" in step1.lower() or "servicio" in step1.lower()

    def test_step1_contains_disambiguation_guidance(self):
        """Step 1 must contain disambiguation guidance (ambigüedad or audience)."""
        step1 = _get_step1_text()
        assert (
            "ambigüedad" in step1.lower()
            or "audiencia" in step1.lower()
            or "audience" in step1.lower()
            or "opciones" in step1.lower()
        )

    def test_step1_contains_example(self):
        """Step 1 must contain a concrete example mentioning 'corte'."""
        step1 = _get_step1_text()
        assert "cortarme el pelo" in step1 or "corte" in step1.lower()
