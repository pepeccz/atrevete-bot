"""
Integration tests for mode prompts.

Tests verify that mode-specific prompts load correctly and reference
shared content properly.
"""

import pytest
from pathlib import Path

from agent.prompts.loader import load_markdown


class TestEscalationModePrompt:
    """Test cases for escalation.md mode prompt."""

    def test_escalation_prompt_loads(self):
        """Test that escalation.md loads successfully."""
        content = load_markdown("escalation.md", "modes")

        assert isinstance(content, str)
        assert len(content) > 500

    def test_escalation_prompt_has_objective(self):
        """Test that escalation prompt has objective section."""
        content = load_markdown("escalation.md", "modes")

        assert "## Objetivo" in content or "## Objective" in content

    def test_escalation_prompt_has_silence_rule(self):
        """Test that escalation prompt has post-escalation silence rule."""
        content = load_markdown("escalation.md", "modes")

        assert "Silencio" in content or "silencio" in content.lower()

    def test_escalation_prompt_has_time_estimate(self):
        """Test that escalation prompt mentions response time estimate."""
        content = load_markdown("escalation.md", "modes")

        assert "5" in content and "10" in content and "minuto" in content

    def test_escalation_prompt_has_examples(self):
        """Test that escalation prompt has usage examples."""
        content = load_markdown("escalation.md", "modes")

        # Should have example code blocks or usage examples
        assert "```" in content or "escalate_to_human" in content


class TestBookingModePrompt:
    """Per-leaf booking prompts (replaced monolithic booking.md in Phase 8)."""

    def test_ask_service_prompt_loads(self):
        """ask_service.md must exist and have content."""
        content = load_markdown("ask_service.md", "modes/booking")
        assert isinstance(content, str)
        assert len(content) > 50

    def test_ask_audience_prompt_loads(self):
        """ask_audience.md must exist and have content."""
        content = load_markdown("ask_audience.md", "modes/booking")
        assert isinstance(content, str)
        assert len(content) > 50

    def test_error_recovery_prompt_loads(self):
        """error_recovery.md must exist and have content."""
        content = load_markdown("error_recovery.md", "modes/booking")
        assert isinstance(content, str)
        assert len(content) > 50

    def test_show_confirmation_prompt_loads(self):
        """show_confirmation.md must exist and have content."""
        content = load_markdown("show_confirmation.md", "modes/booking")
        assert isinstance(content, str)
        assert len(content) > 50


class TestGeneralModePrompt:
    """Test cases for general.md mode prompt."""

    def test_general_prompt_loads(self):
        """Test that general.md loads successfully."""
        content = load_markdown("general.md", "modes")

        assert isinstance(content, str)
        assert len(content) > 1000

    def test_general_prompt_has_read_only_restriction(self):
        """Test that general prompt mentions read-only restriction."""
        content = load_markdown("general.md", "modes")

        # Should mention read-only or restricted tools
        assert (
            "Solo Lectura" in content
            or "solo lectura" in content.lower()
            or "lectura" in content.lower()
        )

    def test_general_prompt_handles_uncertainty_objection(self):
        """Test that general prompt handles 'not sure what I need' scenario."""
        content = load_markdown("general.md", "modes")

        # general.md has "Respuesta ante Indecisión" — "Si el cliente no sabe qué necesita"
        assert "no sabe" in content.lower() or "indecis" in content.lower()

    def test_general_prompt_has_service_advice(self):
        """Test that general prompt has service advice section."""
        content = load_markdown("general.md", "modes")

        # Should have service guidance
        assert "Asesoramiento" in content or "servicios" in content.lower()


class TestGreetingModePrompt:
    """Test cases for greeting.md mode prompt."""

    def test_greeting_prompt_loads(self):
        """Test that greeting.md loads successfully."""
        content = load_markdown("greeting.md", "modes")

        assert isinstance(content, str)
        assert len(content) > 100

    def test_greeting_prompt_has_welcome_message(self):
        """Test that greeting prompt has welcome message guidance."""
        content = load_markdown("greeting.md", "modes")

        # Should mention greeting or welcome
        assert "bienvenida" in content.lower() or "saludo" in content.lower()


class TestSharedContentReferences:
    """Test cases for shared content references in mode prompts."""

    def test_shared_glossary_exists(self):
        """Test that shared/glossary.md exists and has content."""
        content = load_markdown("glossary.md", "shared")

        assert isinstance(content, str)
        assert len(content) > 1000
        assert "#" in content  # Markdown headers

    def test_shared_identity_exists(self):
        """Test that shared/identity.md exists and has content."""
        content = load_markdown("identity.md", "shared")

        assert isinstance(content, str)
        assert len(content) > 100
        assert "Maite" in content

    def test_shared_critical_rules_exists(self):
        """Test that shared/critical_rules.md exists and has content."""
        content = load_markdown("critical_rules.md", "shared")

        assert isinstance(content, str)
        assert len(content) > 100

    def test_shared_recovery_exists(self):
        """Test that legacy/recovery.md exists and has content."""
        content = load_markdown("recovery.md", "legacy")

        assert isinstance(content, str)
        assert len(content) > 100


class TestPromptFileStructure:
    """Test cases for prompt file structure and organization."""

    def test_all_mode_prompts_exist(self):
        """Test that all expected mode prompts exist.

        Note: booking.md was replaced by per-leaf prompts in booking/ (Phase 8).
        booking/ subdirectory is tested by test_booking_subgraph/test_prompts.py.
        """
        prompt_dir = Path(__file__).parent.parent.parent / "agent" / "prompts"
        modes_dir = prompt_dir / "modes"

        # booking.md removed — subgraph uses per-leaf prompts in booking/ dir
        expected_files = ["greeting.md", "general.md", "escalation.md"]

        for filename in expected_files:
            file_path = modes_dir / filename
            assert file_path.exists(), f"Mode prompt missing: {filename}"

    def test_all_shared_prompts_exist(self):
        """Test that all expected shared prompts exist."""
        prompt_dir = Path(__file__).parent.parent.parent / "agent" / "prompts"
        shared_dir = prompt_dir / "shared"
        legacy_dir = prompt_dir / "legacy"

        shared_files = ["identity.md", "critical_rules.md", "glossary.md"]
        legacy_files = ["recovery.md"]

        for filename in shared_files:
            file_path = shared_dir / filename
            assert file_path.exists(), f"Shared prompt missing: {filename}"

        for filename in legacy_files:
            file_path = legacy_dir / filename
            assert file_path.exists(), f"Legacy prompt missing: {filename}"

    def test_mode_prompts_use_markdown(self):
        """Test that all mode prompts use markdown format.

        Note: booking.md removed — subgraph uses per-leaf prompts.
        """
        modes = ["greeting.md", "general.md", "escalation.md"]

        for mode_file in modes:
            content = load_markdown(mode_file, "modes")
            # Should have markdown elements
            assert "#" in content, f"{mode_file} missing markdown headers"

    def test_shared_prompts_use_markdown(self):
        """Test that all shared prompts use markdown format."""
        shared_files = ["identity.md", "critical_rules.md", "glossary.md"]
        legacy_files = ["recovery.md"]

        for shared_file in shared_files:
            content = load_markdown(shared_file, "shared")
            # Should have markdown elements
            assert "#" in content, f"{shared_file} missing markdown headers"

        for legacy_file in legacy_files:
            content = load_markdown(legacy_file, "legacy")
            # Should have markdown elements
            assert "#" in content, f"{legacy_file} missing markdown headers"


class TestPromptContentQuality:
    """Test cases for prompt content quality."""

    def test_booking_prompt_has_emoji_examples(self):
        """Test that booking prompts use emojis appropriately (per-leaf architecture)."""
        from pathlib import Path
        booking_dir = Path(__file__).parent.parent.parent / "agent" / "prompts" / "modes" / "booking"
        # Check combined content of all leaf prompts for emojis
        all_content = " ".join(
            (booking_dir / f).read_text(encoding="utf-8")
            for f in booking_dir.iterdir()
            if f.suffix == ".md"
        )
        emoji_chars = ["✅", "🎯", "📅", "👤", "✓", "💕", "😊", "⚠️"]
        has_emoji = any(emoji in all_content for emoji in emoji_chars)
        assert has_emoji, "Booking leaf prompts should contain emojis"

    def test_escalation_prompt_has_time_frames(self):
        """Test that escalation prompt specifies time frames."""
        content = load_markdown("escalation.md", "modes")

        # Should have time estimates
        assert "5" in content and "10" in content
        assert "minuto" in content

    def test_general_prompt_has_examples(self):
        """Test that general prompt has concrete examples."""
        content = load_markdown("general.md", "modes")

        # Should have numbered examples
        assert "1." in content or "Ejemplo" in content


class TestPromptToolReferences:
    """Test cases for tool references in prompts."""

    def test_booking_prompt_references_all_tools(self):
        """Booking subgraph uses deterministic nodes — no tool references in leaf prompts.

        The subgraph's fetch_availability and execute_book nodes call tools directly
        (not via LLM tool calls). Leaf prompts are tool-free by design (spec invariant #2).
        This test is intentionally a no-op pass for the per-leaf architecture.
        """
        # Per design: LLM leaf nodes do NOT reference tools — deterministic nodes handle that.
        # This assertion documents the architectural invariant.
        from pathlib import Path
        booking_dir = Path(__file__).parent.parent.parent / "agent" / "prompts" / "modes" / "booking"
        for prompt_file in booking_dir.glob("*.md"):
            if prompt_file.name == "await_confirmation.md":
                continue  # silent no-op — special case
            content = prompt_file.read_text(encoding="utf-8")
            assert "check_availability" not in content, (
                f"{prompt_file.name} should NOT reference check_availability "
                f"— deterministic layer handles tool calls"
            )

    def test_general_prompt_references_escalate_tool(self):
        """Test that general prompt references escalate tool."""
        content = load_markdown("general.md", "modes")

        # escalate is the only active tool in GENERAL mode besides manage_appointments
        assert "escalate" in content


class TestPromptFileLoadingEdgeCases:
    """Test edge cases for prompt file loading."""

    def test_load_markdown_empty_subdir(self):
        """Test loading with empty subdirectory."""
        content = load_markdown("identity.md", "")

        # Should return empty string for invalid subdir
        assert content == ""

    def test_load_markdown_nonexistent_file(self):
        """Test loading non-existent file."""
        content = load_markdown("does_not_exist.md", "shared")

        assert content == ""

    def test_load_markdown_invalid_chars_in_filename(self):
        """Test loading file with invalid characters."""
        content = load_markdown("../../../etc/passwd", "shared")

        # Should return empty string (file doesn't exist)
        assert content == ""
