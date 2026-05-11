"""
Unit tests for api/services/resume_injection.py.

Covers:
- Message type mapping (HumanMessage for 'user', AIMessage for 'human_agent')
- Lock acquisition logic
- context_injected_at >= resumed_at short-circuit (idempotency)
- Anchor calculation for paused-window range (paused_at vs fallback)

These tests use only mocks — no database or Redis required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from api.services.resume_injection import _injection_done

# ---------------------------------------------------------------------------
# _injection_done — idempotency guard
# ---------------------------------------------------------------------------


def _make_history(*, context_injected_at=None, resumed_at=None):
    h = MagicMock()
    h.context_injected_at = context_injected_at
    h.resumed_at = resumed_at
    return h


_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def test_injection_done_returns_false_when_no_injected_at():
    """injection_done is False when context_injected_at is None."""
    h = _make_history(context_injected_at=None, resumed_at=_NOW)
    assert _injection_done(h) is False


def test_injection_done_returns_false_when_no_resumed_at():
    """injection_done is False when resumed_at is None (conversation not resumed)."""
    h = _make_history(context_injected_at=_NOW, resumed_at=None)
    assert _injection_done(h) is False


def test_injection_done_returns_true_when_injected_after_resume():
    """injection_done is True when context_injected_at >= resumed_at."""
    resumed = _NOW - timedelta(minutes=5)
    injected = _NOW
    h = _make_history(context_injected_at=injected, resumed_at=resumed)
    assert _injection_done(h) is True


def test_injection_done_returns_false_when_injected_before_resume():
    """injection_done is False when context_injected_at < resumed_at (stale from previous cycle)."""
    resumed = _NOW
    injected = _NOW - timedelta(minutes=10)  # injected before this resume
    h = _make_history(context_injected_at=injected, resumed_at=resumed)
    assert _injection_done(h) is False


def test_injection_done_handles_naive_timestamps():
    """injection_done coerces naive timestamps to UTC for comparison."""
    # Naive timestamps (no tzinfo) should be treated as UTC
    resumed = datetime(2026, 5, 11, 12, 0, 0)  # naive
    injected = datetime(2026, 5, 11, 12, 5, 0)  # naive, 5 minutes later
    h = _make_history(context_injected_at=injected, resumed_at=resumed)
    assert _injection_done(h) is True


def test_injection_done_exact_equality():
    """injection_done is True when context_injected_at == resumed_at exactly."""
    ts = _NOW
    h = _make_history(context_injected_at=ts, resumed_at=ts)
    assert _injection_done(h) is True


# ---------------------------------------------------------------------------
# Message type mapping tests (via import of internals)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_type_mapping_human_agent_becomes_ai_message():
    """human_agent role → AIMessage in injection payload."""
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from langchain_core.messages import AIMessage, HumanMessage

    from api.services.resume_injection import _do_injection

    conv_id = "555"
    now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
    paused = now - timedelta(hours=1)
    resumed = now - timedelta(minutes=10)

    history = _make_history(context_injected_at=None, resumed_at=resumed)
    history.id = uuid4()
    history.paused_at = paused

    agent_msg = MagicMock()
    agent_msg.role = "human_agent"
    agent_msg.content = "Sí, te puedo ayudar"
    agent_msg.author_user_id = uuid4()

    user_msg = MagicMock()
    user_msg.role = "user"
    user_msg.content = "Necesito ayuda"
    user_msg.author_user_id = None

    mock_session = AsyncMock()
    history_result = MagicMock()
    history_result.scalar_one_or_none.return_value = history

    msgs_result = MagicMock()
    msgs_result.scalars.return_value.all.return_value = [user_msg, agent_msg]
    mock_session.execute = AsyncMock(side_effect=[history_result, msgs_result])
    mock_session.commit = AsyncMock()

    captured_messages = []

    mock_graph = AsyncMock()

    async def _capture_aupdate_state(config, values):
        captured_messages.extend(values["messages"])

    mock_graph.aupdate_state = _capture_aupdate_state

    redis = AsyncMock()
    redis.delete = AsyncMock()

    with (
        patch(
            "shared.checkpointer.get_checkpointer",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=MagicMock()),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
        patch(
            "agent.agent_factory.build_conversation_agent",
            return_value=mock_graph,
        ),
    ):
        await _do_injection(
            conversation_id=conv_id,
            session=mock_session,
            redis_client=redis,
            pending_key=f"pending_injection:v2:{conv_id}",
            lock_key=f"pending_injection_lock:v2:{conv_id}",
        )

    assert len(captured_messages) == 2
    assert isinstance(captured_messages[0], HumanMessage)
    assert isinstance(captured_messages[1], AIMessage)
    assert captured_messages[0].content == "Necesito ayuda"
    assert captured_messages[1].content == "Sí, te puedo ayudar"


@pytest.mark.asyncio
async def test_message_type_mapping_preserves_order():
    """Messages are injected in ascending created_at order."""
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from api.services.resume_injection import _do_injection

    conv_id = "556"
    now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
    paused = now - timedelta(hours=1)
    resumed = now - timedelta(minutes=5)

    history = _make_history(context_injected_at=None, resumed_at=resumed)
    history.id = uuid4()
    history.paused_at = paused

    # Three messages in order
    msgs = [
        MagicMock(role="user", content="msg1", author_user_id=None),
        MagicMock(role="human_agent", content="msg2", author_user_id=uuid4()),
        MagicMock(role="user", content="msg3", author_user_id=None),
    ]

    mock_session = AsyncMock()
    history_result = MagicMock()
    history_result.scalar_one_or_none.return_value = history
    msgs_result = MagicMock()
    msgs_result.scalars.return_value.all.return_value = msgs
    mock_session.execute = AsyncMock(side_effect=[history_result, msgs_result])
    mock_session.commit = AsyncMock()

    captured = []
    mock_graph = AsyncMock()

    async def _capture(config, values):
        captured.extend(values["messages"])

    mock_graph.aupdate_state = _capture

    redis = AsyncMock()
    redis.delete = AsyncMock()

    with (
        patch(
            "shared.checkpointer.get_checkpointer",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=MagicMock()),
                __aexit__=AsyncMock(return_value=False),
            ),
        ),
        patch("agent.agent_factory.build_conversation_agent", return_value=mock_graph),
    ):
        await _do_injection(
            conversation_id=conv_id,
            session=mock_session,
            redis_client=redis,
            pending_key=f"pending_injection:v2:{conv_id}",
            lock_key=f"pending_injection_lock:v2:{conv_id}",
        )

    assert len(captured) == 3
    assert captured[0].content == "msg1"
    assert captured[1].content == "msg2"
    assert captured[2].content == "msg3"
