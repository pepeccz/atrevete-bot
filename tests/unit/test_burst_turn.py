"""Unit tests for RedisTestHarness.execute_burst_turn.

All tests are pure — no live Redis, no live database, no deployed agent.
External calls (inject_message, prepare_response_capture, capture_response,
collect_tool_evidence) are monkeypatched on the harness instance.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from tests.e2e.harness.redis_harness import RedisTestHarness, ToolCallEvidence
from tests.e2e.harness.run_models import QARunIdentity, QARunSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_harness() -> RedisTestHarness:
    """Return a harness wired with AsyncMock clients (no live Redis)."""
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value="1-0")
    return RedisTestHarness(redis_client=redis_client, binary_redis_client=AsyncMock())


def _make_session(harness: RedisTestHarness, conversation_id: str = "burst-conv-001") -> QARunSession:
    """Return a fresh QARunSession bound to a test identity."""
    import time

    identity = QARunIdentity(
        conversation_id=conversation_id,
        customer_phone="+34999000001",
        sender_name="QA Burst Tester",
        run_started_at=datetime.now(UTC),
    )
    return harness.create_session(identity=identity)


def _fake_capture_response(conversation_id: str) -> dict[str, Any]:
    """Minimal capture_response return value."""
    now = datetime.now(UTC)
    return {
        "conversation_id": conversation_id,
        "customer_phone": "+34999000001",
        "message": "Hola! ¿Qué servicio querés?",
        "messages": ["Hola! ¿Qué servicio querés?"],
        "timestamp_first_captured": now,
        "timestamp_captured": now,
        "raw_payloads": [{"conversation_id": conversation_id, "message": "Hola! ¿Qué servicio querés?"}],
        "raw_payload": {"conversation_id": conversation_id, "message": "Hola! ¿Qué servicio querés?"},
    }


# ---------------------------------------------------------------------------
# (a) prepare_response_capture is called BEFORE any inject_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_before_inject() -> None:
    """prepare_response_capture must be called before the first inject_message."""
    harness = _make_harness()
    session = _make_session(harness)

    call_order: list[str] = []

    async def fake_prepare() -> None:
        call_order.append("prepare")

    async def fake_inject(**kwargs: Any) -> str:
        call_order.append(f"inject:{kwargs['message_text']}")
        return "1-0"

    harness.prepare_response_capture = fake_prepare  # type: ignore[method-assign]
    harness.inject_message = fake_inject  # type: ignore[method-assign]
    harness.capture_response = AsyncMock(
        return_value=_fake_capture_response(session.identity.conversation_id)
    )
    harness.collect_tool_evidence = AsyncMock(return_value=[])

    await harness.execute_burst_turn(
        user_messages=["hola", "quiero cortarme el pelo"],
        session=session,
        inter_message_delay=0.0,
    )

    assert call_order[0] == "prepare", "prepare_response_capture must be first"
    assert "inject:hola" in call_order
    assert "inject:quiero cortarme el pelo" in call_order
    # prepare must precede ALL injects
    prepare_idx = call_order.index("prepare")
    for item in call_order:
        if item.startswith("inject:"):
            assert call_order.index(item) > prepare_idx


# ---------------------------------------------------------------------------
# (b) inject_message called once per message, IN ORDER
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inject_called_in_order() -> None:
    """inject_message must be called exactly once per message in list order."""
    harness = _make_harness()
    session = _make_session(harness)

    injected: list[str] = []

    async def fake_inject(*, conversation_id: str, message_text: str, **kwargs: Any) -> str:  # noqa: ARG001
        injected.append(message_text)
        return "1-0"

    harness.prepare_response_capture = AsyncMock()
    harness.inject_message = fake_inject  # type: ignore[method-assign]
    harness.capture_response = AsyncMock(
        return_value=_fake_capture_response(session.identity.conversation_id)
    )
    harness.collect_tool_evidence = AsyncMock(return_value=[])

    messages = ["hola", "quiero cortarme el pelo", "para mañana"]
    await harness.execute_burst_turn(
        user_messages=messages,
        session=session,
        inter_message_delay=0.0,
    )

    assert injected == messages, f"Expected {messages}, got {injected}"


# ---------------------------------------------------------------------------
# (c) capture_response called exactly ONCE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_response_called_once() -> None:
    """capture_response must be called exactly once regardless of burst size."""
    harness = _make_harness()
    session = _make_session(harness)

    harness.prepare_response_capture = AsyncMock()
    harness.inject_message = AsyncMock(return_value="1-0")
    mock_capture = AsyncMock(
        return_value=_fake_capture_response(session.identity.conversation_id)
    )
    harness.capture_response = mock_capture
    harness.collect_tool_evidence = AsyncMock(return_value=[])

    await harness.execute_burst_turn(
        user_messages=["msg1", "msg2", "msg3"],
        session=session,
        inter_message_delay=0.0,
    )

    mock_capture.assert_called_once()


# ---------------------------------------------------------------------------
# (d) returned dict has burst_messages and burst_size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_return_dict_has_burst_fields() -> None:
    """Result dict must include burst_messages and burst_size."""
    harness = _make_harness()
    session = _make_session(harness)

    messages = ["hola", "quiero un corte"]
    harness.prepare_response_capture = AsyncMock()
    harness.inject_message = AsyncMock(return_value="1-0")
    harness.capture_response = AsyncMock(
        return_value=_fake_capture_response(session.identity.conversation_id)
    )
    harness.collect_tool_evidence = AsyncMock(return_value=[])

    result = await harness.execute_burst_turn(
        user_messages=messages,
        session=session,
        inter_message_delay=0.0,
    )

    assert result["burst_messages"] == messages
    assert result["burst_size"] == len(messages)
    # agent_response must be the merged reply text
    assert result["agent_response"] == "Hola! ¿Qué servicio querés?"


# ---------------------------------------------------------------------------
# (e) session.turn_count incremented by exactly 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_turn_count_increments_by_one() -> None:
    """A burst is one logical turn — turn_count must go up by exactly 1."""
    harness = _make_harness()
    session = _make_session(harness)
    assert session.turn_count == 0

    harness.prepare_response_capture = AsyncMock()
    harness.inject_message = AsyncMock(return_value="1-0")
    harness.capture_response = AsyncMock(
        return_value=_fake_capture_response(session.identity.conversation_id)
    )
    harness.collect_tool_evidence = AsyncMock(return_value=[])

    await harness.execute_burst_turn(
        user_messages=["hola", "quiero cortarme el pelo"],
        session=session,
        inter_message_delay=0.0,
    )

    assert session.turn_count == 1

    # A second burst also increments by 1 (cumulative: 2)
    await harness.execute_burst_turn(
        user_messages=["para mañana"],
        session=session,
        inter_message_delay=0.0,
    )
    assert session.turn_count == 2


# ---------------------------------------------------------------------------
# (bonus) TurnEvidence is appended to session.evidence with joined user_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_appended_to_session() -> None:
    """execute_burst_turn must append one TurnEvidence entry to session.evidence."""
    harness = _make_harness()
    session = _make_session(harness)

    messages = ["hola", "quiero un tinte"]
    harness.prepare_response_capture = AsyncMock()
    harness.inject_message = AsyncMock(return_value="1-0")
    harness.capture_response = AsyncMock(
        return_value=_fake_capture_response(session.identity.conversation_id)
    )
    harness.collect_tool_evidence = AsyncMock(return_value=[
        ToolCallEvidence(
            tool_name="check_availability",
            arguments={"service_names": ["Tinte"]},
            result={"slots": []},
            source="checkpoint",
            timestamp=datetime.now(UTC),
        )
    ])

    await harness.execute_burst_turn(
        user_messages=messages,
        session=session,
        inter_message_delay=0.0,
    )

    assert len(session.evidence) == 1
    ev = session.evidence[0]
    assert ev.user_message == "hola / quiero un tinte"
    assert ev.turn_number == 1
    assert len(ev.tool_evidence) == 1
    assert ev.tool_evidence[0]["tool_name"] == "check_availability"


# ---------------------------------------------------------------------------
# (bonus) timeout path: timed_out=True, no raise when raise_on_timeout=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_does_not_raise_when_flag_false() -> None:
    """When capture_response times out and raise_on_timeout=False, timed_out=True."""
    harness = _make_harness()
    session = _make_session(harness)

    harness.prepare_response_capture = AsyncMock()
    harness.inject_message = AsyncMock(return_value="1-0")
    harness.capture_response = AsyncMock(side_effect=TimeoutError("no reply"))
    harness.collect_tool_evidence = AsyncMock(return_value=[])

    result = await harness.execute_burst_turn(
        user_messages=["hola"],
        session=session,
        inter_message_delay=0.0,
        raise_on_timeout=False,
    )

    assert result["timed_out"] is True
    assert result["agent_response"] is None


@pytest.mark.asyncio
async def test_timeout_raises_when_flag_true() -> None:
    """When raise_on_timeout=True, TimeoutError must propagate."""
    harness = _make_harness()
    session = _make_session(harness)

    harness.prepare_response_capture = AsyncMock()
    harness.inject_message = AsyncMock(return_value="1-0")
    harness.capture_response = AsyncMock(side_effect=TimeoutError("no reply"))
    harness.collect_tool_evidence = AsyncMock(return_value=[])

    with pytest.raises(TimeoutError):
        await harness.execute_burst_turn(
            user_messages=["hola"],
            session=session,
            inter_message_delay=0.0,
            raise_on_timeout=True,
        )
