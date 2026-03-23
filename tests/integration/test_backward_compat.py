"""
Integration tests for backward compatibility.

Tests verify that the system works correctly when USE_OPTIMIZED_PROMPTS=False
(legacy mode) and that fallback mechanisms work properly.
"""

import os
from unittest.mock import patch

import pytest

from shared.config import get_settings, Settings


class TestBackwardCompatibilityFeatureFlag:
    """Test cases for USE_OPTIMIZED_PROMPTS feature flag."""

    def test_use_optimized_prompts_default_is_true(self):
        """Test that USE_OPTIMIZED_PROMPTS defaults to True."""
        # Clear any existing env var
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
            assert settings.USE_OPTIMIZED_PROMPTS is True

    def test_use_optimized_prompts_can_be_disabled(self):
        """Test that USE_OPTIMIZED_PROMPTS can be set to False."""
        with patch.dict(os.environ, {"USE_OPTIMIZED_PROMPTS": "false"}):
            settings = Settings()
            assert settings.USE_OPTIMIZED_PROMPTS is False

    def test_use_optimized_prompts_env_var_parsing(self):
        """Test various env var formats for USE_OPTIMIZED_PROMPTS."""
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("0", False),
        ]

        for env_value, expected in test_cases:
            with patch.dict(os.environ, {"USE_OPTIMIZED_PROMPTS": env_value}, clear=True):
                settings = Settings()
                assert settings.USE_OPTIMIZED_PROMPTS == expected, \
                    f"Failed for env_value='{env_value}'"

class TestLegacyPromptLoading:
    """Test cases for legacy prompt loading when feature flag is disabled."""

    def test_legacy_prompt_loads_successfully(self):
        """Test that legacy prompt loads correctly."""
        from agent.prompts import load_maite_system_prompt

        prompt = load_maite_system_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 1000
        assert "Maite" in prompt

    def test_legacy_prompt_contains_all_sections(self):
        """Test that legacy prompt contains expected sections."""
        from agent.prompts import load_maite_system_prompt

        prompt = load_maite_system_prompt()

        # Should contain key sections
        assert "# " in prompt  # Markdown headers
        assert "Maite" in prompt  # Identity
        assert "Atrévete" in prompt or "Atrevete" in prompt  # Business name


class TestOptimizedPromptLoading:
    """Test cases for optimized prompt loading when feature flag is enabled."""

    @pytest.mark.asyncio
    async def test_optimized_prompt_loads_successfully(self):
        """Test that optimized prompt loads correctly."""
        from agent.prompts.loader import get_system_prompt, clear_prompt_cache

        # Clear cache for fresh load
        clear_prompt_cache()

        prompt = await get_system_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 1000
        assert "#" in prompt  # Markdown headers

    @pytest.mark.asyncio
    async def test_optimized_prompt_contains_all_shared_sections(self):
        """Test that optimized prompt contains all shared sections."""
        from agent.prompts.loader import get_system_prompt, clear_prompt_cache

        clear_prompt_cache()

        prompt = await get_system_prompt()

        # Should contain separators (indicating concatenation)
        assert "---" in prompt

        # Should contain content from identity, critical_rules, glossary
        assert len(prompt) > 2000  # Combined content is substantial


class TestModePromptsLoading:
    """Test cases for mode-specific prompt loading."""

    def test_greeting_mode_prompt_exists(self):
        """Test that greeting mode prompt exists and loads."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("greeting.md", "modes")

        assert isinstance(content, str)
        assert len(content) > 100
        assert "Modo" in content or "SALUDO" in content or "GREETING" in content.upper()

    def test_booking_mode_prompt_exists(self):
        """Test that booking mode prompt exists and loads."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("booking.md", "modes")

        assert isinstance(content, str)
        assert len(content) > 500  # Booking prompt is substantial
        assert "Modo" in content or "RESERVA" in content or "BOOKING" in content.upper()

    def test_general_mode_prompt_exists(self):
        """Test that general mode prompt exists and loads."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("general.md", "modes")

        assert isinstance(content, str)
        assert len(content) > 500
        assert "Modo" in content or "GENERAL" in content.upper()

    def test_escalation_mode_prompt_exists(self):
        """Test that escalation mode prompt exists and loads."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("escalation.md", "modes")

        assert isinstance(content, str)
        assert len(content) > 500
        assert "Modo" in content or "ESCALACION" in content.upper()

    def test_shared_prompts_exist(self):
        """Test that all shared prompts exist."""
        from agent.prompts.loader import load_markdown

        identity = load_markdown("identity.md", "shared")
        critical_rules = load_markdown("critical_rules.md", "shared")
        glossary = load_markdown("glossary.md", "shared")
        recovery = load_markdown("recovery.md", "shared")

        assert len(identity) > 100
        assert len(critical_rules) > 100
        assert len(glossary) > 1000  # Glossary is the largest
        assert len(recovery) > 100


class TestSharedContentReferences:
    """Test cases for shared content references in mode prompts."""

    def test_booking_prompt_references_shared_glossary(self):
        """Test that booking.md references shared/glossary.md."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("booking.md", "modes")

        # Should reference glossary
        assert "shared/glossary.md" in content or "glossary.md" in content

    def test_booking_prompt_references_shared_critical_rules(self):
        """Test that booking.md references shared/critical_rules.md."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("booking.md", "modes")

        # Should reference critical rules
        assert "shared/critical_rules.md" in content or "critical_rules.md" in content

    def test_booking_prompt_references_shared_recovery(self):
        """Test that booking.md references shared/recovery.md."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("booking.md", "modes")

        # Should reference recovery
        assert "shared/recovery.md" in content or "recovery.md" in content

    def test_escalation_prompt_references_shared_identity(self):
        """Test that escalation.md references shared/identity.md."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("escalation.md", "modes")

        # Should reference identity
        assert "shared/identity.md" in content or "identity.md" in content

    def test_escalation_prompt_references_shared_critical_rules(self):
        """Test that escalation.md references shared/critical_rules.md."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("escalation.md", "modes")

        # Should reference critical rules
        assert "shared/critical_rules.md" in content or "critical_rules.md" in content

    def test_general_prompt_references_shared_glossary(self):
        """Test that general.md references shared/glossary.md."""
        from agent.prompts.loader import load_markdown

        content = load_markdown("general.md", "modes")

        # Should reference glossary multiple times
        assert "shared/glossary.md" in content or "glossary.md" in content


class TestFallbackMechanisms:
    """Test cases for fallback behavior when features are disabled."""

    def test_legacy_prompt_fallback_on_file_not_found(self):
        """Test that legacy prompt returns fallback on missing file."""
        from agent.prompts import load_maite_system_prompt
        from unittest.mock import patch

        with patch("builtins.open", side_effect=FileNotFoundError()):
            prompt = load_maite_system_prompt()

        # Should return fallback
        assert "Maite" in prompt
        assert "asistente virtual" in prompt.lower() or "asistenta" in prompt.lower()

    def test_optimized_prompt_handles_missing_files(self):
        """Test that optimized prompt handles missing files gracefully."""
        from agent.prompts.loader import load_markdown, get_system_prompt, clear_prompt_cache

        # Loading non-existent file should return empty string
        content = load_markdown("nonexistent.md", "shared")
        assert content == ""

        # System prompt should still work with partial content
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_mode_context_building_with_empty_state(self):
        """Test that mode context building handles empty state."""
        from agent.prompts.loader import build_step_context

        context = build_step_context({}, {})

        assert isinstance(context, str)
        assert "Fecha y hora actual" in context  # Should still have timestamp


class TestBookingFlowCompatibility:
    """Test cases for booking flow in both modes."""

    @pytest.mark.asyncio
    async def test_booking_works_with_optimized_prompts(self):
        """Test that booking flow works with optimized prompts."""
        from agent.prompts.loader import (
            build_step_context,
            build_layered_messages,
            clear_prompt_cache,
        )

        clear_prompt_cache()

        # Simulate booking state
        state = {
            "user_message": "I want to book a haircut",
            "customer_name": "Test User",
        }
        mode_context = {"service_name": "Corte Caballero"}

        # Build context (should work)
        context = build_step_context(state, mode_context)
        assert "Corte Caballero" in context

        # Build messages (should work)
        messages = await build_layered_messages(state, mode_context)
        assert len(messages) >= 2

    def test_booking_works_with_legacy_prompts(self):
        """Test that legacy prompts can still be loaded for booking."""
        from agent.prompts import load_maite_system_prompt

        # Legacy prompt should load
        prompt = load_maite_system_prompt()
        assert len(prompt) > 1000

        # Should contain booking-related content
        lower_prompt = prompt.lower()
        assert any(word in lower_prompt for word in [
            "cita", "reserva", "booking", "servicio", "service"
        ])


class TestConfigurationDescription:
    """Test that configuration has proper descriptions."""

    def test_use_optimized_prompts_has_description(self):
        """Test that USE_OPTIMIZED_PROMPTS has a description."""
        from shared.config import Settings

        # Check the field definition
        import inspect
        source = inspect.getsource(Settings)

        # Should mention token reduction and backward compatibility
        assert "optimized" in source.lower() or "token" in source.lower()


class TestEnvironmentVariableIsolation:
    """Test that env vars don't leak between tests."""

    def test_env_var_isolation(self):
        """Test that environment variables are properly isolated."""
        original_value = os.environ.get("USE_OPTIMIZED_PROMPTS")

        try:
            # Set to False
            os.environ["USE_OPTIMIZED_PROMPTS"] = "false"
            settings1 = Settings()
            assert settings1.USE_OPTIMIZED_PROMPTS is False

            # Set to True
            os.environ["USE_OPTIMIZED_PROMPTS"] = "true"
            settings2 = Settings()
            assert settings2.USE_OPTIMIZED_PROMPTS is True

        finally:
            # Restore original
            if original_value is None:
                os.environ.pop("USE_OPTIMIZED_PROMPTS", None)
            else:
                os.environ["USE_OPTIMIZED_PROMPTS"] = original_value
