"""Unit tests for api.services.window_service.compute_window_open.

Two-tier source of truth:
  - Tier 1 (preferred): cached ``can_reply`` mirrored from Chatwoot webhook,
    used when ``can_reply_captured_at`` is younger than 24h.
  - Tier 2 (fallback): ``MAX(created_at) WHERE role='user'`` legacy computation.

Covers SC-4 boundary behaviour plus the new cached-vs-fallback decision logic.
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


def _make_session(
    cached_can_reply: bool | None,
    cached_captured_at: datetime | None,
    last_user_message_at: datetime | None,
) -> AsyncMock:
    """Build a session mock for the two execute calls compute_window_open issues.

    Args:
        cached_can_reply: the bool stored on ConversationHistory.can_reply,
            or None to simulate an absent / un-cached row.
        cached_captured_at: timestamp of capture, or None.
        last_user_message_at: MAX(created_at) WHERE role='user', or None.

    When ``cached_can_reply`` is None and ``cached_captured_at`` is None, the
    first execute returns a row of (None, None) — matching what Postgres returns
    for a row that exists but has no capture yet.
    """
    session = AsyncMock()

    cached_result = MagicMock()
    cached_result.first.return_value = (cached_can_reply, cached_captured_at)

    fallback_result = MagicMock()
    fallback_result.scalar_one_or_none.return_value = last_user_message_at

    session.execute = AsyncMock(side_effect=[cached_result, fallback_result])
    return session


def _legacy_session(last_user_message_at: datetime | None) -> AsyncMock:
    """Session mock simulating no cached value — only the timestamp fallback."""
    return _make_session(
        cached_can_reply=None,
        cached_captured_at=None,
        last_user_message_at=last_user_message_at,
    )


# ---------------------------------------------------------------------------
# Tier 1: cached can_reply path
# ---------------------------------------------------------------------------


class TestCachedCanReplyPath:
    """Cached can_reply is trusted when captured_at is fresh (<24h old)."""

    @pytest.mark.asyncio
    async def test_fresh_cache_true_returns_open(self):
        last_msg = datetime.now(tz=UTC) - timedelta(hours=2)
        session = _make_session(
            cached_can_reply=True,
            cached_captured_at=datetime.now(tz=UTC) - timedelta(minutes=10),
            last_user_message_at=last_msg,
        )
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is True
        assert ts is not None

    @pytest.mark.asyncio
    async def test_fresh_cache_false_returns_closed(self):
        """Even if message timestamps look open, fresh cache=False wins."""
        # Last message looks recent (5h ago) but Chatwoot said can_reply=False
        # — e.g. inbox configured for an API channel with custom window.
        last_msg = datetime.now(tz=UTC) - timedelta(hours=5)
        session = _make_session(
            cached_can_reply=False,
            cached_captured_at=datetime.now(tz=UTC) - timedelta(minutes=10),
            last_user_message_at=last_msg,
        )
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is False
        assert ts is not None  # fallback ts still returned for context

    @pytest.mark.asyncio
    async def test_stale_cache_falls_back_to_timestamp(self):
        """captured_at older than 24h is considered stale — fall through to legacy."""
        # Cache says False but it's 25h old. Legacy computation sees a recent
        # message → window opens.
        last_msg = datetime.now(tz=UTC) - timedelta(hours=2)
        session = _make_session(
            cached_can_reply=False,
            cached_captured_at=datetime.now(tz=UTC) - timedelta(hours=25),
            last_user_message_at=last_msg,
        )
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is True  # legacy wins
        assert ts is not None


# ---------------------------------------------------------------------------
# Tier 2: legacy MAX(created_at) fallback (SC-4 boundary)
# ---------------------------------------------------------------------------


class TestLegacyFallback:
    """When no cache is available, use MAX(created_at) WHERE role='user'."""

    @pytest.mark.asyncio
    async def test_window_open_when_last_message_5h_ago(self):
        last_msg = datetime.now(tz=UTC) - timedelta(hours=5)
        session = _legacy_session(last_msg)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is True
        assert ts is not None
        assert ts.tzinfo is not None

    @pytest.mark.asyncio
    async def test_window_closed_when_last_message_25h_ago(self):
        last_msg = datetime.now(tz=UTC) - timedelta(hours=25)
        session = _legacy_session(last_msg)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is False
        assert ts is not None

    @pytest.mark.asyncio
    async def test_window_closed_at_exact_24h(self):
        last_msg = datetime.now(tz=UTC) - WINDOW_DURATION
        session = _legacy_session(last_msg)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is False

    @pytest.mark.asyncio
    async def test_window_open_just_under_24h(self):
        last_msg = datetime.now(tz=UTC) - WINDOW_DURATION + timedelta(seconds=1)
        session = _legacy_session(last_msg)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is True

    @pytest.mark.asyncio
    async def test_window_closed_when_no_user_messages(self):
        session = _legacy_session(None)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is False
        assert ts is None

    @pytest.mark.asyncio
    async def test_returns_timezone_aware_timestamp(self):
        naive_dt = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        assert naive_dt.tzinfo is None

        session = _legacy_session(naive_dt)
        conv_id = uuid4()

        open_, ts = await compute_window_open(session, conv_id)

        assert open_ is True
        assert ts is not None
        assert ts.tzinfo is not None

    @pytest.mark.asyncio
    async def test_issues_two_queries(self):
        """compute_window_open issues exactly two execute calls: cache + fallback."""
        last_msg = datetime.now(tz=UTC) - timedelta(hours=1)
        session = _legacy_session(last_msg)
        conv_id = uuid4()

        await compute_window_open(session, conv_id)

        assert session.execute.call_count == 2
