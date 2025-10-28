"""
Unit tests for Maite system prompt loading.

Tests the load_maite_system_prompt() function to ensure it correctly
loads the system prompt from disk and handles errors gracefully.
"""

import logging
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from agent.prompts import load_maite_system_prompt


class TestPromptLoading:
    """Test cases for load_maite_system_prompt function."""

    def test_successful_prompt_load(self):
        """Test that prompt loads successfully from disk."""
        prompt = load_maite_system_prompt()

        # Assert prompt is non-empty
        assert prompt, "Prompt should not be empty"

        # Assert minimum length
        assert len(prompt) > 100, f"Prompt should be >100 characters, got {len(prompt)}"

    def test_prompt_contains_maite_identity(self):
        """Test that prompt contains Maite's name."""
        prompt = load_maite_system_prompt()

        assert "Maite" in prompt, "Prompt should contain 'Maite'"

    def test_prompt_contains_business_name(self):
        """Test that prompt contains business name."""
        prompt = load_maite_system_prompt()

        assert "Atrévete Peluquería" in prompt, "Prompt should contain 'Atrévete Peluquería'"

    def test_prompt_contains_tool_usage_section(self):
        """Test that prompt contains tool usage instructions."""
        prompt = load_maite_system_prompt()

        assert "herramientas" in prompt.lower(), "Prompt should contain 'herramientas' (tool usage section)"

    def test_prompt_contains_escalation_instructions(self):
        """Test that prompt contains escalation function reference."""
        prompt = load_maite_system_prompt()

        assert "escalate_to_human" in prompt, "Prompt should contain 'escalate_to_human' escalation function"

    def test_prompt_contains_emoji_guidance(self):
        """Test that prompt contains emoji examples."""
        prompt = load_maite_system_prompt()

        # Check for signature emojis
        assert "🌸" in prompt, "Prompt should contain 🌸 emoji"
        assert "💕" in prompt, "Prompt should contain 💕 emoji"

    def test_prompt_contains_business_context(self):
        """Test that prompt contains stylist information."""
        prompt = load_maite_system_prompt()

        # Check for stylist names (at least some of them)
        assert "Pilar" in prompt, "Prompt should contain stylist 'Pilar'"
        assert "Marta" in prompt, "Prompt should contain stylist 'Marta'"
        assert "Rosa" in prompt, "Prompt should contain stylist 'Rosa'"

    def test_file_not_found_returns_fallback(self, caplog):
        """Test that missing file returns fallback prompt and logs error."""
        with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
            with caplog.at_level(logging.ERROR):
                prompt = load_maite_system_prompt()

                # Should return fallback prompt
                assert prompt == (
                    "Eres Maite, asistenta virtual de Atrevete Peluqueria. "
                    "Se amable, usa herramientas, y escala cuando sea necesario."
                ), "Should return fallback prompt on FileNotFoundError"

                # Should log error
                assert any("System prompt file not found" in record.message for record in caplog.records), \
                    "Should log FileNotFoundError"

    def test_io_error_returns_fallback(self, caplog):
        """Test that IOError returns fallback prompt and logs error."""
        with patch("builtins.open", side_effect=IOError("Read error")):
            with caplog.at_level(logging.ERROR):
                prompt = load_maite_system_prompt()

                # Should return fallback prompt
                assert prompt == (
                    "Eres Maite, asistenta virtual de Atrevete Peluqueria. "
                    "Se amable, usa herramientas, y escala cuando sea necesario."
                ), "Should return fallback prompt on IOError"

                # Should log error
                assert any("Error reading system prompt file" in record.message for record in caplog.records), \
                    "Should log IOError"

    def test_prompt_too_short_returns_fallback(self, caplog):
        """Test that a prompt <100 characters triggers fallback."""
        short_prompt = "Too short"

        with patch("builtins.open", mock_open(read_data=short_prompt)):
            with caplog.at_level(logging.ERROR):
                prompt = load_maite_system_prompt()

                # Should return fallback prompt
                assert prompt == (
                    "Eres Maite, asistenta virtual de Atrevete Peluqueria. "
                    "Se amable, usa herramientas, y escala cuando sea necesario."
                ), "Should return fallback prompt when prompt is too short"

                # Should log error
                assert any("System prompt too short" in record.message for record in caplog.records), \
                    "Should log error about short prompt"

    def test_successful_load_logs_info(self, caplog):
        """Test that successful load logs info message."""
        with caplog.at_level(logging.INFO):
            prompt = load_maite_system_prompt()

            # Should log success with character count
            assert any("Loaded Maite system prompt" in record.message for record in caplog.records), \
                "Should log successful load"

    def test_prompt_file_exists(self):
        """Test that the prompt file actually exists at expected location."""
        # Get the expected path relative to the project root
        expected_path = Path(__file__).parent.parent.parent / "agent" / "prompts" / "maite_system_prompt.md"

        assert expected_path.exists(), f"Prompt file should exist at {expected_path}"
        assert expected_path.is_file(), f"Prompt path should be a file: {expected_path}"

    def test_prompt_uses_utf8_encoding(self):
        """Test that prompt can be read with UTF-8 encoding (Spanish characters)."""
        prompt = load_maite_system_prompt()

        # Check for Spanish accented characters
        spanish_chars = ["á", "é", "í", "ó", "ú", "ñ", "Á", "É", "Í", "Ó", "Ú", "Ñ"]
        has_spanish_char = any(char in prompt for char in spanish_chars)

        assert has_spanish_char, "Prompt should contain Spanish accented characters (UTF-8 encoded)"
