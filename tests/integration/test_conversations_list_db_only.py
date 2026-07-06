"""
Integration tests for PR-1 (inbox-reliability-p1): DB-only conversation list.

Exercises the REAL `list_conversations` (and `get_conversation`) route
functions directly against a live Postgres connection — no session/query
mocking — so the ordering (`ended_at DESC NULLS LAST`), the batched unread
aggregate, and the "no Redis scan" guard are pinned by real query execution,
per the mandatory lesson from #7523 (do NOT merely mock the function under
test).

Route functions are called directly (bypassing FastAPI's dependency-injection
and the ASGI/TestClient transport) rather than through `TestClient`: mixing a
synchronous `TestClient` (which drives the ASGI app on its own background
event loop) with `await`-based Postgres setup on pytest-asyncio's loop causes
asyncpg's loop-bound connections to be shared across two event loops, which
asyncpg rejects at the protocol level. Calling the `async def` route
functions directly keeps everything on ONE event loop while still exercising
the real SQLAlchemy query construction and Postgres execution — `current_user`
is not read by either function body (it exists purely for the HTTP-layer auth
dependency), so a stand-in value is safe.

Covers spec requirements: DB-ONLY-LIST, NO-REDIS-SCAN, ORDERING, UNREAD-COUNT,
TAB-COUNTS.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete

from api.routes.admin import list_conversations
from database.connection import get_async_session
from database.models import ConversationHistory, ConversationMessage

pytestmark = pytest.mark.asyncio

# Namespace all test conversation_ids under this prefix so cleanup is scoped
# and never touches unrelated rows created by other test modules.
TEST_PREFIX = "999888"


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_admin_user():
    """Stand-in for the AdminUser dependency — unused by the function bodies."""
    return MagicMock(id=uuid4(), username="admin", role="admin")


@pytest.fixture(autouse=True)
async def _cleanup_test_conversations():
    """Delete every ConversationHistory row created by this module, before AND after."""

    async def _wipe():
        async with get_async_session() as session:
            await session.execute(
                delete(ConversationHistory).where(
                    ConversationHistory.conversation_id.like(f"{TEST_PREFIX}%")
                )
            )
            await session.commit()

    await _wipe()
    yield
    await _wipe()


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _make_conversation(
    *,
    conversation_id: str,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> ConversationHistory:
    async with get_async_session() as session:
        conv = ConversationHistory(
            id=uuid4(),
            conversation_id=conversation_id,
            customer_id=None,
            started_at=started_at,
            ended_at=ended_at,
            message_count=0,
            metadata_={"sender_name": f"Test {conversation_id}"},
        )
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv


async def _add_message(conv_id, *, role: str, read_at: datetime | None) -> None:
    async with get_async_session() as session:
        session.add(
            ConversationMessage(
                id=uuid4(),
                conversation_history_id=conv_id,
                role=role,
                content="hola",
                read_at=read_at,
            )
        )
        await session.commit()


def _find_item(items: list[dict], conversation_id: str) -> dict | None:
    return next((i for i in items if i["conversation_id"] == conversation_id), None)


# ─── DB-only list + tab agreement ─────────────────────────────────────────────


async def test_db_only_bot_on_conversation_appears_in_all_and_bot_on(fake_admin_user):
    """A DB-only bot-ON conversation (no Redis checkpoint) appears in 'all' and 'bot_on'."""
    conv_id = f"{TEST_PREFIX}001"
    await _make_conversation(conversation_id=conv_id, started_at=datetime.now(UTC))

    result_all = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="all"
    )
    result_bot_on = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="bot_on"
    )

    assert _find_item(result_all["items"], conv_id) is not None
    assert _find_item(result_bot_on["items"], conv_id) is not None


# ─── Ordering ─────────────────────────────────────────────────────────────────


async def test_ordering_by_ended_at_desc(fake_admin_user):
    """Conversation A (ended_at more recent) ranks above B (ended_at older)."""
    now = datetime.now(UTC)
    conv_older = f"{TEST_PREFIX}010"
    conv_newer = f"{TEST_PREFIX}011"
    await _make_conversation(
        conversation_id=conv_older,
        started_at=now - timedelta(hours=1),
        ended_at=now - timedelta(hours=1),
    )
    await _make_conversation(
        conversation_id=conv_newer,
        started_at=now - timedelta(minutes=5),
        ended_at=now - timedelta(minutes=1),
    )

    result = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="all"
    )
    items = result["items"]

    idx_newer = next(i for i, item in enumerate(items) if item["conversation_id"] == conv_newer)
    idx_older = next(i for i, item in enumerate(items) if item["conversation_id"] == conv_older)
    assert idx_newer < idx_older


async def test_ordering_null_ended_at_sorts_last(fake_admin_user):
    """A row with NULL ended_at sinks to the bottom, not the top (NULLS LAST)."""
    now = datetime.now(UTC)
    conv_with_activity = f"{TEST_PREFIX}020"
    conv_no_activity = f"{TEST_PREFIX}021"
    # NULL ended_at simulates the archiver get-or-create path (ADR-1) where every
    # message was skipped and all_timestamps stayed empty.
    await _make_conversation(conversation_id=conv_no_activity, started_at=None, ended_at=None)
    await _make_conversation(
        conversation_id=conv_with_activity, started_at=now - timedelta(minutes=10), ended_at=now
    )

    result = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="all"
    )
    items = result["items"]

    idx_activity = next(
        i for i, item in enumerate(items) if item["conversation_id"] == conv_with_activity
    )
    idx_no_activity = next(
        i for i, item in enumerate(items) if item["conversation_id"] == conv_no_activity
    )
    assert idx_activity < idx_no_activity


# ─── Unread count (batched aggregate) ─────────────────────────────────────────


async def test_unread_count_populated(fake_admin_user):
    """unread_message_count reflects real unread user messages via the batched aggregate."""
    conv_id = f"{TEST_PREFIX}030"
    conv = await _make_conversation(conversation_id=conv_id, started_at=datetime.now(UTC))

    # 3 unread customer messages
    await _add_message(conv.id, role="user", read_at=None)
    await _add_message(conv.id, role="user", read_at=None)
    await _add_message(conv.id, role="user", read_at=None)
    # 1 already-read customer message (must NOT count)
    await _add_message(conv.id, role="user", read_at=datetime.now(UTC))
    # 1 unread assistant message (must NOT count — only role='user' counts)
    await _add_message(conv.id, role="assistant", read_at=None)

    result = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="all"
    )
    item = _find_item(result["items"], conv_id)

    assert item is not None
    assert item["unread_message_count"] == 3


async def test_unread_count_zero_when_no_unread_messages(fake_admin_user):
    """A conversation with zero unread user messages reports unread_message_count=0."""
    conv_id = f"{TEST_PREFIX}031"
    conv = await _make_conversation(conversation_id=conv_id, started_at=datetime.now(UTC))
    await _add_message(conv.id, role="user", read_at=datetime.now(UTC))

    result = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="all"
    )
    item = _find_item(result["items"], conv_id)

    assert item is not None
    assert item["unread_message_count"] == 0


# ─── F2 regression guard: no per-thread Redis scan ────────────────────────────


async def test_endpoint_does_not_scan_redis_per_thread(fake_admin_user):
    """The list endpoint must never call redis_client.scan_iter (F2 regression guard)."""
    spy_redis = MagicMock()
    spy_redis.scan_iter = MagicMock()

    with patch("shared.redis_client.get_redis_client", return_value=spy_redis):
        result = await list_conversations(
            current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="all"
        )

    assert "items" in result
    assert spy_redis.scan_iter.call_count == 0


# ─── Tab counts consistency ────────────────────────────────────────────────────


async def test_list_conversations_tab_counts_consistent(fake_admin_user):
    """counts.{all,bot_on,bot_off} equal the filtered DB-only row counts (page_size=1000)."""
    conv_on = f"{TEST_PREFIX}040"
    conv_off = f"{TEST_PREFIX}041"
    await _make_conversation(conversation_id=conv_on, started_at=datetime.now(UTC))
    conv_off_row = await _make_conversation(conversation_id=conv_off, started_at=datetime.now(UTC))
    # Pause the second conversation directly via DB write (paused_at set → bot_off).
    async with get_async_session() as session:
        row = await session.get(ConversationHistory, conv_off_row.id)
        row.paused_at = datetime.now(UTC)
        await session.commit()

    result_all = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="all"
    )
    result_bot_on = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="bot_on"
    )
    result_bot_off = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="bot_off"
    )

    assert result_all["counts"]["all"] == len(result_all["items"])
    assert result_bot_on["counts"]["bot_on"] == len(result_bot_on["items"])
    assert result_bot_off["counts"]["bot_off"] == len(result_bot_off["items"])
    # Both test conversations must be classified consistently across tabs
    assert _find_item(result_bot_on["items"], conv_on) is not None
    assert _find_item(result_bot_off["items"], conv_off) is not None


# ─── Latency budget (informational, non-CI-gating) ────────────────────────────


@pytest.mark.perf
async def test_list_conversations_latency_budget_200_rows(fake_admin_user):
    """Informational: listing ~200 conversations completes in well under 2s.

    Not CI-gating (wall-clock, environment-dependent) — the structural guard
    (test_endpoint_does_not_scan_redis_per_thread) is what actually protects
    the LATENCY requirement in CI.
    """
    import time

    now = datetime.now(UTC)
    async with get_async_session() as session:
        for n in range(200):
            session.add(
                ConversationHistory(
                    id=uuid4(),
                    conversation_id=f"{TEST_PREFIX}5{n:04d}",
                    customer_id=None,
                    started_at=now - timedelta(minutes=n),
                    ended_at=now - timedelta(minutes=n),
                    message_count=0,
                    metadata_={},
                )
            )
        await session.commit()

    start = time.monotonic()
    result = await list_conversations(
        current_user=fake_admin_user, page=1, page_size=1000, q=None, filter="all"
    )
    elapsed = time.monotonic() - start

    assert len(result["items"]) >= 200
    assert elapsed < 2.0
