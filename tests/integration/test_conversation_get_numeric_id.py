"""
Integration tests for PR-1 (inbox-reliability-p1), ADR-2b: bare numeric
Chatwoot conversation_id resolution on GET /conversations/{conversation_id}.

The Redis-only `/live` endpoint cannot resolve paused/inactive/archived
conversations (their checkpoint is flushed/absent) — exactly the conversations
targeted by notification deep-links. This DB-backed branch closes that gap:
a bare all-digits `conversation_id` is looked up against
`ConversationHistory.conversation_id` and resolved to its UUID `id`.

Exercises the real `get_conversation` route function directly against a live
Postgres connection (see test_conversations_list_db_only.py docstring for why
route functions are called directly instead of through TestClient).

Covers spec requirement: Deep-link thread-open for DB-only conversations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from api.routes.admin import get_conversation
from database.connection import get_async_session
from database.models import ConversationHistory

pytestmark = pytest.mark.asyncio

TEST_PREFIX = "999777"


@pytest.fixture
def fake_admin_user():
    return MagicMock(id=uuid4(), username="admin", role="admin")


@pytest.fixture(autouse=True)
async def _cleanup_test_conversations():
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


async def _make_paused_conversation(*, conversation_id: str) -> ConversationHistory:
    async with get_async_session() as session:
        conv = ConversationHistory(
            id=uuid4(),
            conversation_id=conversation_id,
            customer_id=None,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            paused_at=datetime.now(UTC),
            message_count=0,
            metadata_={"sender_name": "Test Numeric Deep Link"},
        )
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv


async def test_numeric_id_resolves_paused_inactive_conversation(fake_admin_user):
    """A bare numeric Chatwoot id resolves to the conversation's UUID id, even paused/inactive."""
    conv_id = f"{TEST_PREFIX}001"
    conv = await _make_paused_conversation(conversation_id=conv_id)

    result = await get_conversation(conversation_id=conv_id, current_user=fake_admin_user)

    assert result["id"] == str(conv.id)
    assert result["conversation_id"] == conv_id
    assert result["source"] == "db"


async def test_numeric_id_404_when_absent(fake_admin_user):
    """A numeric id with no matching ConversationHistory row raises 404."""
    absent_id = f"{TEST_PREFIX}999999"

    with pytest.raises(HTTPException) as exc_info:
        await get_conversation(conversation_id=absent_id, current_user=fake_admin_user)

    assert exc_info.value.status_code == 404


async def test_uuid_lookup_still_works_unaffected(fake_admin_user):
    """Existing UUID-string lookup path is unaffected by the new numeric-id branch."""
    conv_id = f"{TEST_PREFIX}002"
    conv = await _make_paused_conversation(conversation_id=conv_id)

    result = await get_conversation(conversation_id=str(conv.id), current_user=fake_admin_user)

    assert result["id"] == str(conv.id)
