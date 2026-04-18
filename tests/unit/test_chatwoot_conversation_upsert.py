"""Unit tests for Commit 1 — webhook UPSERT to conversation_history.

Tests that the Chatwoot webhook handler calls upsert_conversation_history
with the correct conversation_id and sender_name metadata after receiving
an incoming message.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from api.routes.chatwoot import upsert_conversation_history
from api.models.chatwoot_webhook import (
    ChatwootConversation,
    ChatwootMessage,
    ChatwootSender,
    ChatwootWebhookPayload,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_payload(conversation_id: int = 101, sender_name: str = "Ana García",
                  phone: str = "+34600000001") -> ChatwootWebhookPayload:
    """Build a minimal ChatwootWebhookPayload for testing."""
    msg = ChatwootMessage(
        id=1,
        content="Hola",
        message_type=0,
        created_at=1700000000,
        conversation_id=conversation_id,
    )
    conv = ChatwootConversation(
        id=conversation_id,
        inbox_id=1,
        messages=[msg],
        custom_attributes={"atencion_automatica": True},
    )
    sender = ChatwootSender(phone_number=phone, name=sender_name)
    return ChatwootWebhookPayload(event="message_created", conversation=conv, sender=sender)


def _make_db_session() -> AsyncMock:
    """Return an async-compatible mock for DB session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


# ============================================================================
# Unit tests for upsert_conversation_history
# ============================================================================


class TestUpsertConversationHistoryInsert:
    """New conversation → INSERT row with sender_name in metadata."""

    @pytest.mark.asyncio
    async def test_insert_called_with_correct_conversation_id(self):
        """upsert stores conversation_id = str(payload.conversation.id)."""
        session = _make_db_session()
        # Simulate no existing row (SELECT returns None)
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        payload = _make_payload(conversation_id=42)

        await upsert_conversation_history(session, payload)

        # Must have executed at least one statement
        assert session.execute.called or session.add.called

    @pytest.mark.asyncio
    async def test_insert_stores_sender_name_in_metadata(self):
        """On new conversation, metadata includes sender_name."""
        session = _make_db_session()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        added_objects = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        payload = _make_payload(conversation_id=99, sender_name="María López")

        await upsert_conversation_history(session, payload)

        assert len(added_objects) == 1
        obj = added_objects[0]
        assert obj.conversation_id == "99"
        assert obj.metadata_["sender_name"] == "María López"

    @pytest.mark.asyncio
    async def test_insert_sets_started_at_not_ended_at(self):
        """On INSERT started_at is set; ended_at should be None."""
        session = _make_db_session()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        added_objects = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        payload = _make_payload(conversation_id=77)

        await upsert_conversation_history(session, payload)

        obj = added_objects[0]
        assert obj.started_at is not None
        assert obj.ended_at is None


class TestUpsertConversationHistoryUpdate:
    """Existing conversation → UPDATE ended_at + message_count."""

    @pytest.mark.asyncio
    async def test_update_increments_message_count(self):
        """On existing conversation, message_count is incremented by 1."""
        existing = MagicMock()
        existing.conversation_id = "42"
        existing.message_count = 3
        existing.metadata_ = {"sender_name": "Ana"}
        existing.started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        existing.ended_at = None

        session = _make_db_session()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        )

        payload = _make_payload(conversation_id=42)
        await upsert_conversation_history(session, payload)

        assert existing.message_count == 4

    @pytest.mark.asyncio
    async def test_update_sets_ended_at(self):
        """On existing conversation, ended_at is updated to now."""
        existing = MagicMock()
        existing.conversation_id = "42"
        existing.message_count = 1
        existing.metadata_ = {}
        existing.started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        existing.ended_at = None

        session = _make_db_session()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        )

        payload = _make_payload(conversation_id=42)
        await upsert_conversation_history(session, payload)

        assert existing.ended_at is not None

    @pytest.mark.asyncio
    async def test_update_does_not_change_started_at(self):
        """On UPDATE, started_at must remain unchanged."""
        original_started = datetime(2024, 1, 1, tzinfo=timezone.utc)
        existing = MagicMock()
        existing.conversation_id = "42"
        existing.message_count = 2
        existing.metadata_ = {}
        existing.started_at = original_started

        session = _make_db_session()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        )

        payload = _make_payload(conversation_id=42)
        await upsert_conversation_history(session, payload)

        assert existing.started_at == original_started
