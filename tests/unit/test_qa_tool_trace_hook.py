from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.hooks.qa_tool_trace import qa_tool_trace_stream, record_tool_calls
from agent.modes.base import ToolCallRecord
from agent.modes.booking_mode import BookingMode
from agent.state.schemas import create_initial_state


@pytest.mark.asyncio
async def test_record_tool_calls_writes_stream_entries() -> None:
    mock_redis = AsyncMock()

    with patch("agent.hooks.qa_tool_trace.get_redis_client", return_value=mock_redis):
        await record_tool_calls(
            conversation_id="qa-conv",
            turn_index=2,
            tool_events=[
                {
                    "tool_name": "search_services",
                    "arguments": {"query": "corte"},
                    "result": {"count": 1},
                    "source": "hook",
                    "timestamp": datetime(2026, 3, 19, tzinfo=UTC),
                }
            ],
        )

    mock_redis.xadd.assert_awaited_once()
    stream_name, payload = mock_redis.xadd.await_args.args
    assert stream_name == qa_tool_trace_stream("qa-conv")
    assert payload["turn_index"] == "2"
    assert payload["tool_name"] == "search_services"


def test_booking_response_updates_schedule_stream_hook_for_qa_runs() -> None:
    mode = BookingMode(tools=[], llm_client=MagicMock())
    state = create_initial_state("qa-conv", "+34999123456")
    state["customer_name"] = "QA"
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    state["messages"] = [{"role": "user", "content": "Quiero un corte"}]

    tool_events = [
        ToolCallRecord(
            tool_name="search_services",
            arguments={"query": "corte"},
            result={"count": 1},
            timestamp=datetime(2026, 3, 19, tzinfo=UTC),
        )
    ]

    with (
        patch.object(mode, "_maybe_prepend_intro", return_value=("todo bien", False)),
        patch("agent.modes.base.schedule_tool_call_recording") as schedule_mock,
    ):
        updates = mode._response_updates(state, "todo bien", tool_events)

    schedule_mock.assert_called_once()
    assert "qa_tool_trace" in updates
    assert updates["qa_tool_trace"][0]["tool_name"] == "search_services"
