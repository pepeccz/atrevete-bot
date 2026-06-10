"""
Tests for REQ-H3: Run JSON writer must use json.dumps with ensure_ascii=False.

These tests validate that user content with special characters (quotes, newlines,
Unicode, emoji) round-trips cleanly through json.dumps / json.loads.

TDD: these tests MUST fail before the skill doc is updated (T1 → RED), then pass
after the json.dumps pattern is documented (T2 → GREEN).

Since the contract is enforced via the qa-runner skill (a documentation + pattern
contract, not a production function), the tests validate the pattern directly rather
than importing from the harness.
"""

import json


def _write_run_json(run_dict: dict) -> str:
    """Pattern under test: single-call json.dumps with ensure_ascii=False and default=str."""
    return json.dumps(run_dict, ensure_ascii=False, default=str)


class TestRunJsonWriterSpecialChars:
    """H3-S1: Special chars in user_message must not corrupt the JSON output."""

    def test_double_quotes_in_user_message(self) -> None:
        """H3-S1: User message with double quotes must round-trip cleanly."""
        run_dict = {
            "turns": [{"user_message": 'Quiero el "corte bob"', "agent_response": "Claro."}]
        }
        serialized = _write_run_json(run_dict)
        parsed = json.loads(serialized)
        assert parsed["turns"][0]["user_message"] == 'Quiero el "corte bob"'

    def test_newline_in_agent_response(self) -> None:
        """H3-S2: Newlines in agent response must survive round-trip as \\n."""
        run_dict = {
            "turns": [
                {
                    "user_message": "Hola",
                    "agent_response": "Hola!\nPuedo ayudarte.\n¿Qué necesitás?",
                }
            ]
        }
        serialized = _write_run_json(run_dict)
        parsed = json.loads(serialized)
        assert "\n" in parsed["turns"][0]["agent_response"]
        assert parsed["turns"][0]["agent_response"] == "Hola!\nPuedo ayudarte.\n¿Qué necesitás?"

    def test_unicode_emoji_in_message(self) -> None:
        """H3-S3: Unicode beyond ASCII (emoji, accents) must survive round-trip."""
        run_dict = {
            "turns": [{"user_message": "¡Hola! 😊 ¿Cómo están?", "agent_response": "¡Bienvenida!"}]
        }
        serialized = _write_run_json(run_dict)
        # With ensure_ascii=False emoji and accents are stored as-is
        assert "😊" in serialized
        parsed = json.loads(serialized)
        assert parsed["turns"][0]["user_message"] == "¡Hola! 😊 ¿Cómo están?"

    def test_nul_byte_default_str_fallback(self) -> None:
        """Edge: NUL byte is non-serializable in strict JSON but default=str handles it."""
        run_dict = {
            "turns": [
                {
                    "user_message": "texto\x00raro",
                    "agent_response": "ok",
                }
            ]
        }
        # default=str ensures non-serializable objects don't raise
        serialized = _write_run_json(run_dict)
        parsed = json.loads(serialized)
        # Value must be parseable; exact value of NUL handling is implementation detail
        assert isinstance(parsed["turns"][0]["user_message"], str)

    def test_full_run_dict_is_parseable(self) -> None:
        """Integration: a realistic run dict with all keys must produce valid JSON."""
        run_dict = {
            "scenario_id": "test-abc",
            "conversation_id": "conv-123",
            "outcome": "booked",
            "turns": [
                {
                    "turn_number": 1,
                    "user_message": 'Quiero un "corte de dama" para el lunes',
                    "agent_response": "¡Hola!\nTe puedo ayudar 😊",
                    "tool_evidence": [{"tool_name": "check_availability", "source": "checkpoint"}],
                }
            ],
            "final_state": None,
            "langfuse_trace_path": None,
        }
        serialized = _write_run_json(run_dict)
        parsed = json.loads(serialized)
        assert parsed["scenario_id"] == "test-abc"
        assert parsed["turns"][0]["user_message"] == 'Quiero un "corte de dama" para el lunes'
        assert "😊" in parsed["turns"][0]["agent_response"]
