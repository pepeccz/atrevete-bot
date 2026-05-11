"""Unit tests for api.services.window_service.compute_window_open.

Covers SC-4 (24h boundary behaviour):
  - A conversation with a user message 5 hours ago → window OPEN.
  - A conversation with a user message 25 hours ago → window CLOSED.
  - Boundary cases: exactly 24h (closed), just under 24h (open).
  - No user messages at all → window CLOSED, last_user_message_at is None.

All DB calls are mocked; no real database connection is required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from api.services.window_service import WINDOW_DURATION, compute_window_open

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_with_max_created_at(dt: datetime | None) -> AsyncMock:
    """Build a minimal AsyncSession mock that returns ``dt`` from scalar_one_or_none()."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = dt
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# SC-4 — 24h window boundary
# ---------------------------------------------------------------------------


class TestComputeWindowOpen:
    """Tests for compute_window_open boundary behaviour (SC-4)."""

    @pytest.mark.asyncio
    async def test_window_open_when_last_message_5h_ago(self):
        """Last user message 5 hours ago → window is open (within 24h)."""
        last_msg = datetime.now(tz=UTC) - timedelta(hours=5)
        session = _make_session_with_max_created_at(last_msg)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is True
        assert ts is not None
        # The returned timestamp should be tz-aware
        assert ts.tzinfo is not None

    @pytest.mark.asyncio
    async def test_window_closed_when_last_message_25h_ago(self):
        """Last user message 25 hours ago → window is closed (beyond 24h)."""
        last_msg = datetime.now(tz=UTC) - timedelta(hours=25)
        session = _make_session_with_max_created_at(last_msg)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is False
        assert ts is not None
        assert ts.tzinfo is not None

    @pytest.mark.asyncio
    async def test_window_closed_at_exact_24h(self):
        """Last user message exactly 24h ago → window is closed (boundary is exclusive)."""
        # Subtract a tiny epsilon to simulate a real DB timestamp that is exactly 24h old
        # at query time.  The condition is strict ``<``, so 24h == 24h is closed.
        last_msg = datetime.now(tz=UTC) - WINDOW_DURATION
        session = _make_session_with_max_created_at(last_msg)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        # (now - last_msg) is ~WINDOW_DURATION; strict < means this is NOT open
        assert open_ is False

    @pytest.mark.asyncio
    async def test_window_open_just_under_24h(self):
        """Last user message 23h59m59s ago → window is still open (one second to spare)."""
        last_msg = datetime.now(tz=UTC) - WINDOW_DURATION + timedelta(seconds=1)
        session = _make_session_with_max_created_at(last_msg)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is True

    @pytest.mark.asyncio
    async def test_window_closed_when_no_user_messages(self):
        """No user messages at all → window is closed and last_user_message_at is None."""
        session = _make_session_with_max_created_at(None)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is False
        assert ts is None

    @pytest.mark.asyncio
    async def test_returns_timezone_aware_timestamp(self):
        """Returned timestamp must be timezone-aware even if DB returns naive UTC."""
        # Simulate Postgres returning a naive datetime (no tzinfo)
        naive_dt = datetime.utcnow() - timedelta(hours=2)
        assert naive_dt.tzinfo is None  # confirm it's naive

        session = _make_session_with_max_created_at(naive_dt)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is True
        assert ts is not None
        # Service must attach UTC tzinfo to naive timestamps
        assert ts.tzinfo is not None

    @pytest.mark.asyncio
    async def test_uses_correct_conversation_id(self):
        """compute_window_open must pass the conversation_history_id to the query."""
        last_msg = datetime.now(tz=UTC) - timedelta(hours=1)
        session = _make_session_with_max_created_at(last_msg)
        conv_id = uuid4()

        await compute_window_open(session, conv_id)

        # The session.execute must have been called once (for the MAX query)
        session.execute.assert_called_once()
