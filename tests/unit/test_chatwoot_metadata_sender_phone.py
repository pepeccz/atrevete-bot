"""Webhook upsert must persist sender_phone in ConversationHistory.metadata.

Used by the admin inbox CustomerCard to show contact info when a conversation
has no linked customers row yet.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.models.chatwoot_webhook import (
    ChatwootConversation,
    ChatwootMessage,
    ChatwootSender,
    ChatwootWebhookPayload,
)
from api.routes.chatwoot import upsert_conversation_history


def _payload(name: str | None, phone: str | None, conv_id: int = 8):
    sender = ChatwootSender(name=name, phone_number=phone)
    msg = ChatwootMessage(
        id=1,
        content="hi",
        message_type=0,
        content_type="text",
        attachments=[],
        sender=sender,
        created_at=1700000000,
        conversation_id=conv_id,
    )
    return ChatwootWebhookPayload(
        event="message_created",
        conversation=ChatwootConversation(id=conv_id, inbox_id=1, messages=[msg]),
        sender=sender,
        attachments=[],
    )


def _session_with(existing_row, customer_id=None):
    """Order of execute() calls inside upsert_conversation_history:
    1. Customer lookup by phone
    2. ConversationHistory parent lookup by conversation_id
    3. ConversationMessage dup check by chatwoot_message_id
    4. MAX/COUNT for message_count update
    """
    session = AsyncMock()

    customer_result = MagicMock()
    customer_result.scalar_one_or_none.return_value = customer_id

    history_result = MagicMock()
    history_result.scalar_one_or_none.return_value = existing_row

    dup_result = MagicMock()
    dup_result.scalar_one_or_none.return_value = None  # not a duplicate

    count_result = MagicMock()
    count_result.scalar.return_value = 1

    session.execute = AsyncMock(
        side_effect=[customer_result, history_result, dup_result, count_result]
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_new_conversation_stores_sender_phone_and_name():
    session = _session_with(existing_row=None)
    payload = _payload(name="Pepe", phone="+34666123456")

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="hi",
        chatwoot_message_id=1,
    )

    inserted = session.add.call_args_list[0].args[0]
    assert inserted.metadata_["sender_name"] == "Pepe"
    assert inserted.metadata_["sender_phone"] == "+34666123456"


@pytest.mark.asyncio
async def test_existing_conversation_backfills_missing_phone():
    existing = MagicMock()
    existing.customer_id = None
    existing.metadata_ = {"sender_name": "Pepe"}
    session = _session_with(existing_row=existing)
    payload = _payload(name="Pepe", phone="+34666123456")

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="hi",
        chatwoot_message_id=1,
    )

    assert existing.metadata_ == {"sender_name": "Pepe", "sender_phone": "+34666123456"}


@pytest.mark.asyncio
async def test_existing_phone_is_not_overwritten():
    existing = MagicMock()
    existing.customer_id = None
    existing.metadata_ = {"sender_name": "Pepe", "sender_phone": "+34666111111"}
    session = _session_with(existing_row=existing)
    payload = _payload(name="Pepe", phone="+34666222222")

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="hi",
        chatwoot_message_id=1,
    )

    assert existing.metadata_["sender_phone"] == "+34666111111"


@pytest.mark.asyncio
async def test_phone_missing_from_payload_does_not_break():
    session = _session_with(existing_row=None)
    payload = _payload(name="Pepe", phone=None)

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="hi",
        chatwoot_message_id=1,
    )

    inserted = session.add.call_args_list[0].args[0]
    assert inserted.metadata_.get("sender_name") == "Pepe"
    assert "sender_phone" not in inserted.metadata_
