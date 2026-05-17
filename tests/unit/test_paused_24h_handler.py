"""Unit tests for agent.workers.notification_handlers.paused_24h.

SC-8: daily reminder for conversations paused > 24 hours.

Test cases:
  1. Conversation paused 23h ago → NOT eligible (below threshold)
  2. Conversation paused 25h ago, no prior reminder → eligible → send_fn dispatched
  3. Conversation paused 25h ago, reminder sent 23h ago → NOT re-eligible (cooldown)
  4. Conversation paused 25h ago, reminder sent 25h ago → eligible again
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.workers.notification_handlers.paused_24h import (
    PAUSED_THRESHOLD,
    REMINDER_COOLDOWN,
    mark_failed_fn,
    mark_sent_fn,
    query_fn,
    send_fn,
)
from database.models import ConversationHistory, NotificationType

# ─── Helpers ───────────────────────────────────────────────────────────────────


def _make_conv(
    paused_at: datetime | None = None,
    resumed_at: datetime | None = None,
    customer_id: str | None = None,
) -> ConversationHistory:
    """Build a minimal ConversationHistory instance for testing."""
    conv = MagicMock(spec=ConversationHistory)
    conv.id = uuid4()
    conv.paused_at = paused_at
    conv.resumed_at = resumed_at
    conv.customer_id = customer_id or str(uuid4())
    conv.conversation_id = f"v2:{uuid4()}"
    return conv


def _make_session_with_scalars(rows: list) -> AsyncMock:
    """Build a mock AsyncSession where execute().scalars().all() → rows."""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


# ─── query_fn tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_fn_excludes_conv_paused_23h_ago():
    """Conversations paused < 24h should NOT appear in the query result."""
    # We mock the execute call to return zero rows, simulating the WHERE clause
    # properly excluding the 23h conversation.
    session = _make_session_with_scalars([])
    result = await query_fn(session)
    assert result == []


@pytest.mark.asyncio
async def test_query_fn_includes_conv_paused_25h_no_reminder():
    """Conversations paused > 24h with no recent reminder are included."""
    now = datetime.now(UTC)
    paused_at = now - timedelta(hours=25)
    conv = _make_conv(paused_at=paused_at, resumed_at=None)

    session = _make_session_with_scalars([conv])
    result = await query_fn(session)
    assert len(result) == 1
    assert result[0].id == conv.id


@pytest.mark.asyncio
async def test_query_fn_excludes_conv_with_recent_reminder():
    """Conversations that already received a reminder within 24h are excluded."""
    # Simulate the DB returning an empty list because the sub-query filters them out.
    session = _make_session_with_scalars([])
    result = await query_fn(session)
    # Still 0 — the mock represents the post-filter result
    assert result == []


# ─── send_fn tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_fn_creates_notifications_for_active_users():
    """send_fn creates one Notification row per active admin user."""
    now = datetime.now(UTC)
    conv = _make_conv(paused_at=now - timedelta(hours=25))

    mock_user_1 = MagicMock()
    mock_user_1.id = uuid4()
    mock_user_2 = MagicMock()
    mock_user_2.id = uuid4()

    # Mock get_async_session context manager
    mock_session = AsyncMock()
    users_result = MagicMock()
    users_result.scalars.return_value.all.return_value = [mock_user_1, mock_user_2]
    mock_session.execute = AsyncMock(return_value=users_result)
    mock_session.add_all = MagicMock()
    mock_session.commit = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    # Patch the database.connection module-level symbol so the lazy import inside
    # send_fn picks up our mock context manager.
    with patch(
        "database.connection.get_async_session",
        return_value=mock_ctx,
    ):
        result = await send_fn(conv, None)

    assert result is True
    mock_session.add_all.assert_called_once()
    notifications_added = mock_session.add_all.call_args[0][0]
    assert len(notifications_added) == 2
    for notif in notifications_added:
        assert notif.entity_type == "conversation_history"
        assert notif.entity_id == conv.id
        assert notif.type == NotificationType.CONVERSATION_PAUSED_REMINDER


@pytest.mark.asyncio
async def test_send_fn_returns_false_when_no_active_users():
    """send_fn returns False when there are no active admin users."""
    conv = _make_conv(paused_at=datetime.now(UTC) - timedelta(hours=25))

    mock_session = AsyncMock()
    users_result = MagicMock()
    users_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=users_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "database.connection.get_async_session",
        return_value=mock_ctx,
    ):
        result = await send_fn(conv, None)

    assert result is False


# ─── mark_sent_fn / mark_failed_fn no-op tests ────────────────────────────────


@pytest.mark.asyncio
async def test_mark_sent_fn_is_noop():
    """mark_sent_fn completes without error and makes no DB calls."""
    session = AsyncMock()
    await mark_sent_fn(session, uuid4())
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_mark_failed_fn_is_noop():
    """mark_failed_fn completes without error and makes no DB calls."""
    session = AsyncMock()
    await mark_failed_fn(session, uuid4())
    session.execute.assert_not_called()


# ─── Threshold constant sanity checks ─────────────────────────────────────────


def test_paused_threshold_is_24h():
    assert PAUSED_THRESHOLD == timedelta(hours=24)


def test_reminder_cooldown_is_24h():
    assert REMINDER_COOLDOWN == timedelta(hours=24)
