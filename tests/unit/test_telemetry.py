"""Unit tests for per-turn telemetry helpers in agent/main.py.

Tests follow Strict TDD: written RED first, then made GREEN by implementation.

Covered behaviours:
  - _extract_tokens: happy path (usage_metadata present) + absent
  - _extract_tool_calls: tool pairs present + absent + result truncation
  - record_turn: inserts ConversationTurn row with correct latency

Note: record_turn integration (DB insert) is tested via mock session to keep
these pure unit tests with no DB dependency.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# ---------------------------------------------------------------------------
# Helpers under test — imported from agent.main after GREEN implementation
# ---------------------------------------------------------------------------


class TestExtractTokens:
    """Tests for _extract_tokens(messages) -> (tokens_in, tokens_out)."""

    def test_tokens_populated_when_usage_metadata_present(self):
        """AIMessage with usage_metadata -> tokens_in=120, tokens_out=80."""
        from agent.main import _extract_tokens

        ai_msg = AIMessage(
            content="hola",
            usage_metadata={"input_tokens": 120, "output_tokens": 80, "total_tokens": 200},
        )
        tokens_in, tokens_out = _extract_tokens([ai_msg])

        assert tokens_in == 120
        assert tokens_out == 80

    def test_tokens_null_when_usage_metadata_absent(self):
        """AIMessage with usage_metadata=None -> both fields None, no exception."""
        from agent.main import _extract_tokens

        ai_msg = AIMessage(content="hola", usage_metadata=None)
        tokens_in, tokens_out = _extract_tokens([ai_msg])

        assert tokens_in is None
        assert tokens_out is None

    def test_tokens_null_when_no_ai_message(self):
        """Slice with only HumanMessage -> both None."""
        from agent.main import _extract_tokens

        tokens_in, tokens_out = _extract_tokens([HumanMessage(content="user turn")])

        assert tokens_in is None
        assert tokens_out is None

    def test_uses_last_ai_message_when_multiple_present(self):
        """Multiple AIMessages -> last one wins (tool roundtrip scenario)."""
        from agent.main import _extract_tokens

        msgs = [
            AIMessage(
                content="step1",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            ),
            AIMessage(
                content="step2",
                usage_metadata={"input_tokens": 200, "output_tokens": 90, "total_tokens": 290},
            ),
        ]
        tokens_in, tokens_out = _extract_tokens(msgs)

        assert tokens_in == 200
        assert tokens_out == 90


class TestExtractToolCalls:
    """Tests for _extract_tool_calls(messages) -> list | None."""

    def test_tool_calls_null_for_no_tool_turn(self):
        """Slice with no ToolMessage -> None (not empty list)."""
        from agent.main import _extract_tool_calls

        msgs = [HumanMessage(content="quiero una cita"), AIMessage(content="claro")]
        result = _extract_tool_calls(msgs)

        assert result is None

    def test_tool_calls_truncated_to_500(self):
        """ToolMessage result > 500 chars -> result_summary is exactly 500 chars."""
        from agent.main import _extract_tool_calls

        long_result = "x" * 600
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_abc",
                    "name": "check_availability",
                    "args": {"date": "2026-05-01"},
                }
            ],
        )
        tool_msg = ToolMessage(content=long_result, tool_call_id="call_abc")
        result = _extract_tool_calls([ai_msg, tool_msg])

        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "check_availability"
        assert len(result[0]["result_summary"]) == 500

    def test_tool_calls_short_result_not_truncated(self):
        """ToolMessage result <= 500 chars -> stored verbatim."""
        from agent.main import _extract_tool_calls

        short_result = "ok"
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_xyz", "name": "book", "args": {"stylist": "Ana"}}],
        )
        tool_msg = ToolMessage(content=short_result, tool_call_id="call_xyz")
        result = _extract_tool_calls([ai_msg, tool_msg])

        assert result is not None
        assert result[0]["result_summary"] == "ok"

    def test_tool_calls_contains_name_args_result_summary_keys(self):
        """Each entry has exactly {name, args, result_summary}."""
        from agent.main import _extract_tool_calls

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "escalate", "args": {"reason": "complex"}}],
        )
        tool_msg = ToolMessage(content='{"escalated": true}', tool_call_id="call_1")
        result = _extract_tool_calls([ai_msg, tool_msg])

        assert result is not None
        entry = result[0]
        assert set(entry.keys()) == {"name", "args", "result_summary"}
        assert entry["args"] == {"reason": "complex"}


class TestRecordTurn:
    """Tests for record_turn() — DB insert with latency, tokens, tool_calls."""

    @pytest.mark.asyncio
    async def test_turn_row_inserted_with_latency(self):
        """record_turn inserts a ConversationTurn with non-null latency_ms."""
        from agent.main import record_turn

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        # Patch the scalar result for COUNT(*) -> 0 existing turns
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        mock_session.execute = AsyncMock(return_value=count_result)

        conversation_history_id = uuid4()

        with patch("database.connection.get_async_session", return_value=mock_session):
            await record_turn(
                conversation_history_id=conversation_history_id,
                latency_ms=250,
                messages_slice=[],
            )

        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        from database.models import ConversationTurn

        assert isinstance(added_obj, ConversationTurn)
        assert added_obj.latency_ms == 250
        assert added_obj.conversation_history_id == conversation_history_id
