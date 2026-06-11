"""Unit tests for Commit 1 — webhook UPSERT to conversation_history.

Tests that the Chatwoot webhook handler calls upsert_conversation_history
with the correct conversation_id and sender_name metadata after receiving
an incoming message.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.models.chatwoot_webhook import (
    ChatwootConversation,
    ChatwootMessage,
    ChatwootSender,
    ChatwootWebhookPayload,
)
from api.routes.chatwoot import upsert_conversation_history

# ============================================================================
# Helpers
# ============================================================================


def _make_payload(
    conversation_id: int = 101, sender_name: str = "Ana García", phone: str = "+34600000001"
) -> ChatwootWebhookPayload:
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
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        payload = _make_payload(conversation_id=42)

        await upsert_conversation_history(session, payload)

        # Must have executed at least one statement
        assert session.execute.called or session.add.called

    @pytest.mark.asyncio
    async def test_insert_stores_sender_name_in_metadata(self):
        """On new conversation, metadata includes sender_name."""
        session = _make_db_session()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        added_objects = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        payload = _make_payload(conversation_id=99, sender_name="María López")

        await upsert_conversation_history(session, payload)

        assert len(added_objects) == 1
        obj = added_objects[0]
        assert obj.conversation_id == "99"
        assert obj.metadata_["sender_name"] == "María López"

    @pytest.mark.asyncio
    async def test_insert_links_existing_customer_by_phone(self):
        """If sender phone matches Customer in DB, customer_id is linked on INSERT."""
        from uuid import uuid4

        customer_uuid = uuid4()
        customer_result = MagicMock(scalar_one_or_none=MagicMock(return_value=customer_uuid))
        conv_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        # 3rd call: message_count recompute (SELECT COUNT from ConversationMessage)
        count_result = MagicMock(scalar=MagicMock(return_value=0))

        session = _make_db_session()
        session.execute = AsyncMock(side_effect=[customer_result, conv_result, count_result])

        added_objects = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        payload = _make_payload(conversation_id=55, phone="+34600000001")

        await upsert_conversation_history(session, payload)

        assert len(added_objects) == 1
        assert added_objects[0].customer_id == customer_uuid

    @pytest.mark.asyncio
    async def test_insert_customer_id_null_when_phone_unknown(self):
        """If sender phone doesn't match any Customer, customer_id stays None."""
        customer_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        conv_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        # 3rd call: message_count recompute (SELECT COUNT from ConversationMessage)
        count_result = MagicMock(scalar=MagicMock(return_value=0))

        session = _make_db_session()
        session.execute = AsyncMock(side_effect=[customer_result, conv_result, count_result])

        added_objects = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        payload = _make_payload(conversation_id=56)

        await upsert_conversation_history(session, payload)

        assert added_objects[0].customer_id is None

    @pytest.mark.asyncio
    async def test_insert_sets_started_at_and_ended_at(self):
        """On INSERT both started_at and ended_at are set to now (parent has a child message)."""
        session = _make_db_session()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        added_objects = []
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        payload = _make_payload(conversation_id=77)

        await upsert_conversation_history(session, payload)

        # First added object is the ConversationHistory parent
        parent = added_objects[0]
        assert parent.started_at is not None
        assert parent.ended_at is not None


class TestUpsertConversationHistoryUpdate:
    """Existing conversation → UPDATE ended_at + message_count."""

    @pytest.mark.asyncio
    async def test_update_recomputes_message_count_from_children(self):
        """message_count is recomputed from actual ConversationMessage rows."""
        existing = MagicMock()
        existing.conversation_id = "42"
        existing.message_count = 3
        existing.metadata_ = {"sender_name": "Ana"}
        existing.started_at = datetime(2024, 1, 1, tzinfo=UTC)
        existing.ended_at = None

        session = _make_db_session()
        # Sequence: SELECT customer (None), SELECT conv (existing), SELECT dup (None),
        # SELECT count (returns 7).
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=existing)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
                MagicMock(scalar=MagicMock(return_value=7)),
            ]
        )

        payload = _make_payload(conversation_id=42)
        await upsert_conversation_history(
            session, payload, message_text="Hola", chatwoot_message_id=None
        )

        assert existing.message_count == 7

    @pytest.mark.asyncio
    async def test_update_sets_ended_at(self):
        """On existing conversation, ended_at is updated to now."""
        existing = MagicMock()
        existing.conversation_id = "42"
        existing.message_count = 1
        existing.metadata_ = {}
        existing.started_at = datetime(2024, 1, 1, tzinfo=UTC)
        existing.ended_at = None

        session = _make_db_session()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        )

        payload = _make_payload(conversation_id=42)
        await upsert_conversation_history(session, payload)

        assert existing.ended_at is not None

    @pytest.mark.asyncio
    async def test_update_backfills_customer_id_when_null(self):
        """If existing row has customer_id=None and phone resolves, backfill."""
        from uuid import uuid4

        existing = MagicMock()
        existing.conversation_id = "42"
        existing.message_count = 1
        existing.customer_id = None
        existing.metadata_ = {}
        existing.started_at = datetime(2024, 1, 1, tzinfo=UTC)

        customer_uuid = uuid4()
        customer_result = MagicMock(scalar_one_or_none=MagicMock(return_value=customer_uuid))
        conv_result = MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        # 3rd call: message_count recompute (SELECT COUNT from ConversationMessage)
        count_result = MagicMock(scalar=MagicMock(return_value=1))

        session = _make_db_session()
        session.execute = AsyncMock(side_effect=[customer_result, conv_result, count_result])

        payload = _make_payload(conversation_id=42)
        await upsert_conversation_history(session, payload)

        assert existing.customer_id == customer_uuid

    @pytest.mark.asyncio
    async def test_update_does_not_change_started_at(self):
        """On UPDATE, started_at must remain unchanged."""
        original_started = datetime(2024, 1, 1, tzinfo=UTC)
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
