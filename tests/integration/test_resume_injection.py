"""
Integration tests for the resume injection service.

Covers:
- SC-3: Full resume injection cycle — aupdate_state called, context_injected_at set,
        Redis flag deleted
- SC-9: Idempotency — second inbound after injection skips duplicate injection
        (context_injected_at >= resumed_at guard)

These tests mock Redis, SQLAlchemy session, and the LangGraph aupdate_state call —
no live Postgres, Redis, or LangGraph required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from api.services.resume_injection import maybe_inject_pending_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONV_ID = "789"

_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
_PAUSED_AT = _NOW - timedelta(hours=1)
_RESUMED_AT = _NOW - timedelta(minutes=5)


def _make_redis_with_flag(*, flag_exists: bool = True, lock_acquired: bool = True) -> AsyncMock:
    """Return a mock Redis client with configurable flag/lock behavior."""
    r = AsyncMock()
    r.exists = AsyncMock(return_value=1 if flag_exists else 0)
    r.set = AsyncMock(return_value=lock_acquired)  # SETNX via set(nx=True)
    r.delete = AsyncMock()
    return r


def _make_conversation_history(
    *,
    paused_at=_PAUSED_AT,
    resumed_at=_RESUMED_AT,
    context_injected_at=None,
):
    """Return a mock ConversationHistory ORM object."""
    h = MagicMock()
    h.id = uuid4()
    h.conversation_id = CONV_ID
    h.paused_at = paused_at
    h.resumed_at = resumed_at
    h.context_injected_at = context_injected_at
    return h


def _make_conversation_message(role: str, content: str, created_at=None):
    """Return a mock ConversationMessage ORM object."""
    m = MagicMock()
    m.id = uuid4()
    m.role = role
    m.content = content
    m.created_at = created_at or _PAUSED_AT
    m.author_user_id = uuid4() if role == "human_agent" else None
    return m


# ---------------------------------------------------------------------------
# SC-3: Full injection cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_injection_cycle():
    """SC-3: Injection fetches paused-window messages, calls aupdate_state, and cleans up."""
    redis = _make_redis_with_flag(flag_exists=True, lock_acquired=True)

    history = _make_conversation_history()
    user_msg = _make_conversation_message("user", "Hola", created_at=_PAUSED_AT)
    agent_msg = _make_conversation_message(
        "human_agent", "En que te puedo ayudar", created_at=_PAUSED_AT + timedelta(minutes=1)
    )

    mock_session = AsyncMock()

    # First execute: return history; second execute: return messages
    history_result = MagicMock()
    history_result.scalar_one_or_none.return_value = history

    msgs_result = MagicMock()
    msgs_result.scalars.return_value.all.return_value = [user_msg, agent_msg]

    mock_session.execute = AsyncMock(side_effect=[history_result, msgs_result])
    mock_session.commit = AsyncMock()

    mock_graph = AsyncMock()
    mock_graph.aupdate_state = AsyncMock()

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
        result = await maybe_inject_pending_context(
            conversation_id=CONV_ID,
            session=mock_session,
            redis_client=redis,
        )

    assert result is True

    # aupdate_state was called with the correct thread_id
    mock_graph.aupdate_state.assert_called_once()
    call_args = mock_graph.aupdate_state.call_args
    config = call_args[0][0]
    assert config["configurable"]["thread_id"] == f"v2:{CONV_ID}"

    # Messages were passed in order: user first, then human_agent
    messages = call_args[0][1]["messages"]
    assert len(messages) == 2
    # user → HumanMessage, human_agent → AIMessage
    from langchain_core.messages import AIMessage, HumanMessage

    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)

    # context_injected_at was set
    assert history.context_injected_at is not None

    # Redis flag was deleted
    redis.delete.assert_called()
    delete_calls = [str(call) for call in redis.delete.call_args_list]
    assert any("pending_injection" in c for c in delete_calls)


# ---------------------------------------------------------------------------
# SC-9: Idempotency — already injected for this resume cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_skips_second_injection():
    """SC-9: context_injected_at >= resumed_at means injection already done — skip."""
    redis = _make_redis_with_flag(flag_exists=True, lock_acquired=True)

    # Already injected after resume
    history = _make_conversation_history(context_injected_at=_NOW)
    # context_injected_at=NOW >= resumed_at=NOW-5min → already done

    mock_session = AsyncMock()
    history_result = MagicMock()
    history_result.scalar_one_or_none.return_value = history
    mock_session.execute = AsyncMock(return_value=history_result)

    with patch(
        "agent.agent_factory.build_conversation_agent",
    ) as mock_agent:
        result = await maybe_inject_pending_context(
            conversation_id=CONV_ID,
            session=mock_session,
            redis_client=redis,
        )

    # Injection was skipped
    assert result is False
    mock_agent.assert_not_called()

    # Stale flag was cleaned up
    redis.delete.assert_called()


# ---------------------------------------------------------------------------
# No pending flag — fast return
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_pending_flag_returns_false():
    """If no pending_injection flag exists, return False without any DB access."""
    redis = _make_redis_with_flag(flag_exists=False)
    mock_session = AsyncMock()

    result = await maybe_inject_pending_context(
        conversation_id=CONV_ID,
        session=mock_session,
        redis_client=redis,
    )

    assert result is False
    mock_session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Lock not acquired — waits then proceeds without injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_not_acquired_returns_false():
    """If SETNX lock acquisition fails, the loser polls then returns False."""
    redis = _make_redis_with_flag(flag_exists=True, lock_acquired=False)

    # Simulate sibling never setting context_injected_at in time
    history = _make_conversation_history(context_injected_at=None)
    mock_session = AsyncMock()
    history_result = MagicMock()
    history_result.scalar_one_or_none.return_value = history
    mock_session.execute = AsyncMock(return_value=history_result)

    with patch("api.services.resume_injection.asyncio.sleep", new_callable=AsyncMock):
        result = await maybe_inject_pending_context(
            conversation_id=CONV_ID,
            session=mock_session,
            redis_client=redis,
        )

    assert result is False


# ---------------------------------------------------------------------------
# Empty message list — no injection needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_paused_messages_cleans_up_flag():
    """If paused-window is empty (no messages), flag is deleted and False returned."""
    redis = _make_redis_with_flag(flag_exists=True, lock_acquired=True)

    history = _make_conversation_history()

    mock_session = AsyncMock()
    history_result = MagicMock()
    history_result.scalar_one_or_none.return_value = history

    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[history_result, empty_result])

    with patch("agent.agent_factory.build_conversation_agent") as mock_agent:
        result = await maybe_inject_pending_context(
            conversation_id=CONV_ID,
            session=mock_session,
            redis_client=redis,
        )

    assert result is False
    mock_agent.assert_not_called()
    # Flag deleted
    redis.delete.assert_called()
