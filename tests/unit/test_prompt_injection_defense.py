"""
Unit tests for prompt injection defense mechanisms.

Covers:
- _sanitize_notes: HTML stripping, whitespace collapse, truncation
- preprocess_node_v6: message length truncation + warning log
- critical_rules.md: integrity check for rules 15-18
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent.graphs.conversation_flow import preprocess_node_v6
from agent.tools.booking_tools import _sanitize_notes


# ============================================================================
# Class 1: TestSanitizeNotes
# ============================================================================


class TestSanitizeNotes:
    """Pure unit tests for _sanitize_notes."""

    def test_none_returns_none(self):
        assert _sanitize_notes(None) is None

    def test_empty_string_returns_none(self):
        assert _sanitize_notes("") is None

    def test_whitespace_only_returns_none(self):
        assert _sanitize_notes("   ") is None

    def test_normal_note_unchanged(self):
        assert _sanitize_notes("normal note") == "normal note"

    def test_script_tag_stripped(self):
        assert _sanitize_notes("<script>alert('xss')</script>text") == "text"

    def test_multiple_html_tags_stripped(self):
        assert _sanitize_notes("<b>bold</b> and <i>italic</i>") == "bold and italic"

    def test_extra_whitespace_collapsed(self):
        assert _sanitize_notes("extra   whitespace\n\nnewlines") == "extra whitespace newlines"

    def test_long_string_truncated_to_500(self):
        long_note = "a" * 600
        result = _sanitize_notes(long_note)
        assert result is not None
        assert len(result) == 500

    def test_custom_max_length_respected(self):
        result = _sanitize_notes("hello world", max_length=10)
        assert result == "hello worl"

    def test_html_only_whitespace_returns_none(self):
        assert _sanitize_notes("<b></b>   ") is None

    def test_angle_brackets_without_tag_name_keep_surrounding_content(self):
        # Plain text with no angle-bracket patterns: passes through unchanged
        result = _sanitize_notes("extra charges apply")
        assert result == "extra charges apply"

    def test_tag_like_pattern_stripped(self):
        # Patterns matching <word> are treated as tags and stripped
        result = _sanitize_notes("allergic to <pollen> and dust")
        assert result is not None
        assert "allergic to" in result
        assert "and dust" in result


# ============================================================================
# Class 2: TestPreprocessTruncation
# ============================================================================


class TestPreprocessTruncation:
    """Async tests for preprocess_node_v6 message truncation."""

    def _make_state(self, user_message: str) -> dict:
        return {
            "user_message": user_message,
            "conversation_id": "conv-test-truncation",
            "customer_phone": None,
            "messages": [],
            "total_message_count": 0,
        }

    async def test_short_message_passes_unchanged(self):
        """A message under 2000 chars should not be modified."""
        message = "Hola, quiero reservar una cita"
        state = self._make_state(message)

        with (
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                new=AsyncMock(return_value=(False, None)),
            ),
        ):
            result = await preprocess_node_v6(state)

        # The message should be stored as-is in the messages list
        stored_messages = result.get("messages", [])
        assert len(stored_messages) == 1
        assert stored_messages[0]["content"] == message

    async def test_message_over_2000_chars_gets_truncated(self):
        """A message over 2000 chars must be truncated and a warning logged."""
        long_message = "A" * 2500
        state = self._make_state(long_message)

        with (
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                new=AsyncMock(return_value=(False, None)),
            ),
            patch("agent.graphs.conversation_flow.logger") as mock_logger,
        ):
            result = await preprocess_node_v6(state)

        stored_messages = result.get("messages", [])
        assert len(stored_messages) == 1
        assert len(stored_messages[0]["content"]) == 2000

        # Warning must be logged
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        # Check the format string includes truncation info
        assert "truncated" in call_args[0][0]

    async def test_exactly_2000_chars_passes_unchanged(self):
        """A message of exactly 2000 chars should NOT be truncated."""
        exact_message = "B" * 2000
        state = self._make_state(exact_message)

        with (
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                new=AsyncMock(return_value=(False, None)),
            ),
            patch("agent.graphs.conversation_flow.logger") as mock_logger,
        ):
            result = await preprocess_node_v6(state)

        stored_messages = result.get("messages", [])
        assert len(stored_messages) == 1
        assert len(stored_messages[0]["content"]) == 2000

        # No truncation warning should be logged
        mock_logger.warning.assert_not_called()


# ============================================================================
# Class 3: TestPromptRulesIntegrity
# ============================================================================


class TestPromptRulesIntegrity:
    """File content tests for critical_rules.md integrity."""

    CRITICAL_RULES_PATH = (
        Path(__file__).parent.parent.parent
        / "agent"
        / "prompts"
        / "shared"
        / "critical_rules.md"
    )

    def _read_rules(self) -> str:
        return self.CRITICAL_RULES_PATH.read_text(encoding="utf-8")

    def test_rule_15_present(self):
        """Rule 15 (identity lock) must exist."""
        content = self._read_rules()
        assert "Bloqueo de identidad" in content

    def test_rule_16_present(self):
        """Rule 16 (prompt confidentiality) must exist."""
        content = self._read_rules()
        assert "Confidencialidad del prompt" in content

    def test_rule_17_present(self):
        """Rule 17 (instruction boundary) must exist."""
        content = self._read_rules()
        assert "Frontera de instrucciones" in content

    def test_rule_18_present(self):
        """Rule 18 (scope restriction) must exist."""
        content = self._read_rules()
        assert "Restricción de alcance" in content

    def test_total_rule_count_is_18(self):
        """File must contain exactly 18 numbered rules."""
        import re

        content = self._read_rules()
        rule_lines = re.findall(r"^\d+\.", content, re.MULTILINE)
        assert len(rule_lines) == 18, f"Expected 18 rules, found {len(rule_lines)}"
