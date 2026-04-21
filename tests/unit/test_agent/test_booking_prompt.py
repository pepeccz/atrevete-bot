"""
Unit tests for booking prompt architecture — per-leaf prompt system.

Phase 8 migration: the monolithic booking.md was replaced by per-leaf prompt files
under agent/prompts/modes/booking/. These tests assert the per-leaf architecture.
"""

from pathlib import Path

_BOOKING_PROMPTS_DIR = (
    Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "modes" / "booking"
)


class TestBookingPromptStep1:
    """ask_service.md must describe the service resolution flow (replaces booking.md Step 1)."""

    def test_ask_service_prompt_exists(self):
        """ask_service.md must exist in the per-leaf prompts directory."""
        prompt_path = _BOOKING_PROMPTS_DIR / "ask_service.md"
        assert prompt_path.exists(), "ask_service.md not found in agent/prompts/modes/booking/"

    def test_ask_service_references_catalog_or_service(self):
        """ask_service.md must reference service identification."""
        content = (_BOOKING_PROMPTS_DIR / "ask_service.md").read_text(encoding="utf-8")
        assert "catálogo" in content.lower() or "servicio" in content.lower()

    def test_ask_service_contains_disambiguation_guidance(self):
        """ask_service.md must contain disambiguation guidance (audience or dimensión)."""
        content = (_BOOKING_PROMPTS_DIR / "ask_service.md").read_text(encoding="utf-8")
        assert (
            "dimension" in content.lower()
            or "audience" in content.lower()
            or "señora" in content.lower()
            or "opciones" in content.lower()
        )

    def test_ask_service_contains_example(self):
        """ask_service.md must contain a concrete example mentioning 'corte'."""
        content = (_BOOKING_PROMPTS_DIR / "ask_service.md").read_text(encoding="utf-8")
        assert "cortarme el pelo" in content or "corte" in content.lower()
