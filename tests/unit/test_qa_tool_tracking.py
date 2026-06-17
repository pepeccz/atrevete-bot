from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from tests.e2e.harness.redis_harness import (
    CheckpointToolEvidenceAdapter,
    RedisTestHarness,
    StreamToolEvidenceAdapter,
    ToolCallEvidence,
    validate_tool_trace,
)
from tests.e2e.harness.run_models import QARunIdentity


@pytest.mark.asyncio
async def test_checkpoint_adapter_collects_tool_evidence_from_messages() -> None:
    """CheckpointToolEvidenceAdapter reads AIMessage.tool_calls + ToolMessages.

    The old qa_tool_trace field does not exist in AgentState; tool data lives
    in state["messages"] (SSOT: agent/main.py:_extract_tool_calls).
    """
    from langchain_core.messages import AIMessage, ToolMessage

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_abc",
                "name": "check_availability",
                "args": {"service_names": ["Cortar"], "stylist_name": "Marta"},
            }
        ],
    )
    tool_msg = ToolMessage(
        content='{"slots": []}',
        tool_call_id="call_abc",
    )

    harness = RedisTestHarness(redis_client=AsyncMock(), binary_redis_client=AsyncMock())
    harness.capture_final_state = AsyncMock(
        return_value={"messages": [ai_msg, tool_msg]}
    )

    adapter = CheckpointToolEvidenceAdapter(harness)
    evidence = await adapter.collect("qa-conversation", 1)

    assert [entry.tool_name for entry in evidence] == ["check_availability"]
    assert evidence[0].arguments == {"service_names": ["Cortar"], "stylist_name": "Marta"}
    assert evidence[0].source == "checkpoint"
    assert evidence[0].result["status"] == "success"
    assert '{"slots": []}' in evidence[0].result["result_summary"]


@pytest.mark.asyncio
async def test_stream_adapter_collects_turn_specific_evidence() -> None:
    redis_client = AsyncMock()
    redis_client.xrange = AsyncMock(
        return_value=[
            (
                b"1742385600000-0",
                {
                    b"turn_index": b"1",
                    b"tool_name": b"check_availability",
                    b"args": b'{"service_names": ["Cortar"]}',
                    b"result": b'{"slots": []}',
                    b"source": b"stream",
                },
            ),
            (
                b"1742385601000-0",
                {
                    b"turn_index": b"2",
                    b"tool_name": b"book_appointment",
                    b"args": b"{}",
                    b"result": b'{"success": true}',
                    b"source": b"stream",
                },
            ),
        ]
    )
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())

    adapter = StreamToolEvidenceAdapter(harness)
    evidence = await adapter.collect("qa-conversation", 1)

    assert [entry.tool_name for entry in evidence] == ["check_availability"]
    assert evidence[0].arguments == {"service_names": ["Cortar"]}
    assert evidence[0].result == {"slots": []}
    assert evidence[0].source == "stream"
    assert evidence[0].timestamp == datetime.fromtimestamp(1742385600, tz=UTC)


def test_validate_all_tools_present() -> None:
    evidence = [
        ToolCallEvidence(
            "check_availability",
            {"service_names": ["Cortar"], "stylist_name": "Marta"},
            {},
            "checkpoint",
            datetime.now(UTC),
        ),
        ToolCallEvidence("book", {}, {"success": True}, "checkpoint", datetime.now(UTC)),
    ]

    report = validate_tool_trace(evidence, flow_type="booking")

    assert report.all_required_present is True
    assert report.missing_tools == []
    assert report.out_of_order == []
    assert report.found_tools == [
        "check_availability",
        "book_appointment",
    ]


def test_validate_missing_tool() -> None:
    evidence = [
        ToolCallEvidence("search_services", {}, {}, "checkpoint", datetime.now(UTC)),
        ToolCallEvidence("check_availability", {}, {}, "checkpoint", datetime.now(UTC)),
    ]

    report = validate_tool_trace(evidence, flow_type="booking")

    assert report.all_required_present is False
    assert report.missing_tools == ["book_appointment"]
    assert report.out_of_order == []


def test_validate_out_of_order() -> None:
    # Evidence with book_appointment BEFORE check_availability — genuine out-of-order.
    evidence = [
        ToolCallEvidence(
            "book_appointment", {}, {"success": True}, "checkpoint", datetime.now(UTC)
        ),
        ToolCallEvidence("check_availability", {}, {}, "checkpoint", datetime.now(UTC)),
    ]

    report = validate_tool_trace(evidence, flow_type="booking")

    assert report.all_required_present is False
    assert report.missing_tools == []
    assert report.out_of_order == ["book_appointment", "check_availability"]


def test_validate_non_booking_flow_skips() -> None:
    evidence = [ToolCallEvidence("search_services", {}, {}, "checkpoint", datetime.now(UTC))]

    report = validate_tool_trace(evidence, flow_type="escalation")

    assert report.all_required_present is True
    assert report.found_tools == []
    assert report.missing_tools == []
    assert report.out_of_order == []


@pytest.mark.asyncio
async def test_execute_turn_adds_tool_evidence_to_response() -> None:
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    harness = RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())

    identity = QARunIdentity(
        conversation_id="qa-conversation",
        customer_phone="+34999123456",
        sender_name="QA-booking-1234abcd",
        run_started_at=datetime.now(UTC),
    )
    session = harness.create_session(identity=identity)

    harness.capture_response = AsyncMock(
        return_value={
            "conversation_id": identity.conversation_id,
            "customer_phone": identity.customer_phone,
            "message": "Hola, decime qué servicio queres.",
            "messages": ["Hola, decime qué servicio queres."],
            "timestamp_first_captured": datetime.now(UTC),
            "timestamp_captured": datetime.now(UTC),
            "raw_payloads": [{"conversation_id": identity.conversation_id, "message": "Hola"}],
            "raw_payload": {"conversation_id": identity.conversation_id, "message": "Hola"},
        }
    )
    harness._pubsub = AsyncMock()
    harness.collect_tool_evidence = AsyncMock(
        return_value=[
            ToolCallEvidence(
                tool_name="check_availability",
                arguments={"service_names": ["Cortar"], "stylist_name": "Marta"},
                result={"slots": []},
                source="checkpoint",
                timestamp=datetime.now(UTC),
            )
        ]
    )

    result = await harness.execute_turn(user_message="Hola", session=session)

    assert result["tool_evidence"] == [
        {
            "tool_name": "check_availability",
            "arguments": {"service_names": ["Cortar"], "stylist_name": "Marta"},
            "result": {"slots": []},
            "source": "checkpoint",
            "timestamp": result["tool_evidence"][0]["timestamp"],
        }
    ]
    assert session.evidence[0].tool_evidence == result["tool_evidence"]
