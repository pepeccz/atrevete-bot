"""Unit tests for qa_turn_helper CLI subcommands (AS4, AS5, E2).

Covers:
- _cmd_turn builds QARunIdentity + QARunSession from CLI args and passes them to execute_turn
- _cmd_turn JSON output has required fields: agent_response, timed_out, response_latency_ms, tool_evidence
- _cmd_state does NOT output current_mode, mode_context, mode_history
- _cmd_state does output messages_count and latest_tool_call_name
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _cmd_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_turn_uses_qarunidentity_and_session() -> None:
    """AS4: _cmd_turn builds QARunIdentity + QARunSession and passes session to execute_turn."""
    conv_id = str(uuid.uuid4())
    phone = "+34999000001"
    name = "María"
    message = "Quiero reservar una cita"

    mock_result = {
        "turn_number": 1,
        "user_message": message,
        "agent_response": "Hola, con gusto te ayudo.",
        "timestamp_sent": datetime.now(UTC).isoformat(),
        "timestamp_received": datetime.now(UTC).isoformat(),
        "response_latency_ms": 500,
        "timed_out": False,
        "raw_payloads": [],
        "tool_evidence": [],
    }

    captured_output = {}

    def capture_print(data: dict) -> None:
        captured_output.update(data)

    with (
        patch("tests.e2e.harness.qa_turn_helper.RedisTestHarness") as MockHarness,
        patch("tests.e2e.harness.qa_turn_helper.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(REDIS_URL="redis://localhost:6379", REDIS_PASSWORD="")

        instance = AsyncMock()
        instance.execute_turn = AsyncMock(return_value=mock_result)
        instance.close = AsyncMock()
        MockHarness.return_value = instance

        from tests.e2e.harness.qa_turn_helper import _cmd_turn

        args = MagicMock()
        args.conversation_id = conv_id
        args.user_message = message
        args.customer_phone = phone
        args.persona_name = name
        args.timeout = 60.0

        with patch("builtins.print") as mock_print:
            await _cmd_turn(args)

    # Verify execute_turn was called with a QARunSession (not raw kwargs)
    instance.execute_turn.assert_called_once()
    call_kwargs = instance.execute_turn.call_args.kwargs
    assert "session" in call_kwargs
    session = call_kwargs["session"]
    assert session.identity.conversation_id == conv_id
    assert session.identity.customer_phone == phone
    assert session.identity.sender_name == name
    assert isinstance(session.identity.run_started_at, datetime)
    assert "user_message" in call_kwargs
    assert call_kwargs["user_message"] == message

    # Verify JSON output has required fields
    printed_json = mock_print.call_args.args[0]
    data = json.loads(printed_json)
    assert "agent_response" in data
    assert "timed_out" in data
    assert "response_latency_ms" in data
    assert "tool_evidence" in data


@pytest.mark.asyncio
async def test_cmd_turn_output_has_required_fields() -> None:
    """AS4: _cmd_turn JSON output must include agent_response, timed_out, response_latency_ms, tool_evidence."""
    conv_id = str(uuid.uuid4())

    mock_result = {
        "turn_number": 1,
        "user_message": "Hola",
        "agent_response": "Hola, ¿en qué te puedo ayudar?",
        "timestamp_sent": datetime.now(UTC).isoformat(),
        "timestamp_received": datetime.now(UTC).isoformat(),
        "response_latency_ms": 123,
        "timed_out": False,
        "raw_payloads": [],
        "tool_evidence": [{"tool_name": "check_availability", "arguments": {}, "result": {}, "source": "checkpoint", "timestamp": "..."}],
    }

    with (
        patch("tests.e2e.harness.qa_turn_helper.RedisTestHarness") as MockHarness,
        patch("tests.e2e.harness.qa_turn_helper.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(REDIS_URL="redis://localhost:6379", REDIS_PASSWORD="")
        instance = AsyncMock()
        instance.execute_turn = AsyncMock(return_value=mock_result)
        instance.close = AsyncMock()
        MockHarness.return_value = instance

        from tests.e2e.harness.qa_turn_helper import _cmd_turn

        args = MagicMock()
        args.conversation_id = conv_id
        args.user_message = "Hola"
        args.customer_phone = "+34999000001"
        args.persona_name = "Test"
        args.timeout = 30.0

        with patch("builtins.print") as mock_print:
            await _cmd_turn(args)

    printed_json = mock_print.call_args.args[0]
    data = json.loads(printed_json)
    assert data["agent_response"] == "Hola, ¿en qué te puedo ayudar?"
    assert data["timed_out"] is False
    assert data["response_latency_ms"] == 123
    assert len(data["tool_evidence"]) == 1


# ---------------------------------------------------------------------------
# _cmd_state — deleted fields must not appear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_state_does_not_output_deleted_fields() -> None:
    """AS5: _cmd_state must NOT output current_mode, mode_context, or mode_history."""
    conv_id = str(uuid.uuid4())

    # Simulate a checkpoint state that has these legacy fields (should be ignored)
    fake_state = {
        "conversation_id": conv_id,
        "customer_phone": "+34999000001",
        "customer_id": None,
        "customer_name": "Test",
        "messages": ["msg1", "msg2"],
        "customer_consents": [],
        "policy_accepted_at": None,
        "summary": None,
        # Legacy fields that must NOT appear in output
        "current_mode": "booking",
        "mode_context": {"step": 1},
        "mode_history": ["idle", "booking"],
        "is_first_interaction": True,
        "error_count": 0,
    }

    with (
        patch("tests.e2e.harness.qa_turn_helper.RedisTestHarness") as MockHarness,
        patch("tests.e2e.harness.qa_turn_helper.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(REDIS_URL="redis://localhost:6379", REDIS_PASSWORD="")
        instance = AsyncMock()
        instance.capture_final_state = AsyncMock(return_value=fake_state)
        instance.close = AsyncMock()
        MockHarness.return_value = instance

        from tests.e2e.harness.qa_turn_helper import _cmd_state

        args = MagicMock()
        args.conversation_id = conv_id

        with patch("builtins.print") as mock_print:
            await _cmd_state(args)

    printed_json = mock_print.call_args.args[0]
    data = json.loads(printed_json)

    # Must NOT be present
    assert "current_mode" not in data, "current_mode must not appear in _cmd_state output"
    assert "mode_context" not in data, "mode_context must not appear in _cmd_state output"
    assert "mode_history" not in data, "mode_history must not appear in _cmd_state output"
    assert "is_first_interaction" not in data, "is_first_interaction must not appear in _cmd_state output"
    assert "error_count" not in data, "error_count must not appear in _cmd_state output"


@pytest.mark.asyncio
async def test_cmd_state_outputs_messages_count_and_latest_tool() -> None:
    """AS5: _cmd_state must output messages_count and latest_tool_call_name."""
    conv_id = str(uuid.uuid4())

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    fake_messages = [
        HumanMessage(content="Hola"),
        AIMessage(content="", tool_calls=[{"name": "check_availability", "args": {}, "id": "t1"}]),
        ToolMessage(content='{"slots": []}', tool_call_id="t1", name="check_availability"),
    ]

    fake_state = {
        "conversation_id": conv_id,
        "customer_phone": "+34999000001",
        "customer_id": None,
        "customer_name": "Test",
        "messages": fake_messages,
        "customer_consents": [],
        "policy_accepted_at": None,
        "summary": "Summary text",
    }

    with (
        patch("tests.e2e.harness.qa_turn_helper.RedisTestHarness") as MockHarness,
        patch("tests.e2e.harness.qa_turn_helper.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock(REDIS_URL="redis://localhost:6379", REDIS_PASSWORD="")
        instance = AsyncMock()
        instance.capture_final_state = AsyncMock(return_value=fake_state)
        instance.close = AsyncMock()
        MockHarness.return_value = instance

        from tests.e2e.harness.qa_turn_helper import _cmd_state

        args = MagicMock()
        args.conversation_id = conv_id

        with patch("builtins.print") as mock_print:
            await _cmd_state(args)

    printed_json = mock_print.call_args.args[0]
    data = json.loads(printed_json)

    assert data["messages_count"] == 3
    assert data["latest_tool_call_name"] == "check_availability"
    assert data["summary_present"] is True
