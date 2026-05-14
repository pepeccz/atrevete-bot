"""
Integration tests for PR-3a — message attachment persistence.

Tests cover:
- Real ``incoming_image.json`` fixture: 1 attachment persisted, file_type='image', correct url
- ``incoming_text.json`` regression: 0 attachments, message still created (text preserved)
- Synthetic 2-attachment payload: both persisted in order with positions 0, 1
- Synthetic attachment without data_url: 0 persisted, no crash, warning logged
- Synthetic content=null + attachments: message persisted (content=''), attachments persisted

All tests drive ``upsert_conversation_history`` directly (no HTTP layer needed for
attachment-persistence logic).  The webhook HTTP integration (gate flow, bot-off, etc.)
is covered by ``test_webhook_gate_refactor.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Fixtures directory
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures" / "chatwoot"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Helpers — mock session that records session.add() calls
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    """Return a mock AsyncSession capturing add() calls and supporting execute/flush."""
    session = AsyncMock()
    session._added: list = []

    def _add(obj):
        session._added.append(obj)

    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()

    # Default execute: return None scalar (no dup, no existing row)
    _no_dup = MagicMock()
    _no_dup.scalar_one_or_none = MagicMock(return_value=None)
    # scalar() for count query
    _no_dup.scalar = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=_no_dup)

    return session


def _build_payload(raw: dict):
    """Parse a raw fixture dict into a ChatwootWebhookPayload."""
    from api.models.chatwoot_webhook import ChatwootWebhookPayload

    return ChatwootWebhookPayload(**raw)


# ---------------------------------------------------------------------------
# Scenario 7.1 — real incoming_image.json: 1 attachment persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_image_fixture_persists_one_attachment():
    """Scenario 7.1: incoming_image.json → 1 MessageAttachment row, file_type='image'."""
    from api.routes.chatwoot import upsert_conversation_history
    from database.models import ConversationMessage, MessageAttachment

    raw = _load_fixture("incoming_image.json")
    payload = _build_payload(raw)

    session = _make_session()

    # Give the ConversationMessage row a UUID so _persist_attachments can use it
    msg_row_id = uuid4()

    # Side-effect: when session.add() is called with a ConversationMessage, stamp its id
    original_add = session.add.side_effect

    def _add_with_id(obj):
        if isinstance(obj, ConversationMessage):
            obj.id = msg_row_id
        original_add(obj)

    session.add.side_effect = _add_with_id

    # Extract raw attachments the same way the webhook handler does
    raw_attachments = (
        [att.model_dump() for att in payload.attachments] if payload.attachments else None
    )

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="",  # content is null in image-only message
        chatwoot_message_id=raw["id"],
        attachments_payload=raw_attachments,
    )

    attachment_rows = [obj for obj in session._added if isinstance(obj, MessageAttachment)]
    assert len(attachment_rows) == 1, "Expected 1 attachment row"

    att = attachment_rows[0]
    assert att.file_type == "image"
    assert "File.jpg" in att.url
    assert att.thumb_url is not None
    assert att.size_bytes == 232934
    assert att.position == 0


# ---------------------------------------------------------------------------
# Scenario: incoming_text.json — 0 attachments, message row still created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_fixture_no_attachments():
    """Regression: text-only message creates ConversationMessage, 0 attachments."""
    from api.routes.chatwoot import upsert_conversation_history
    from database.models import ConversationMessage, MessageAttachment

    raw = _load_fixture("incoming_text.json")
    payload = _build_payload(raw)

    session = _make_session()

    raw_attachments = (
        [att.model_dump() for att in payload.attachments] if payload.attachments else None
    )

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="Hola",
        chatwoot_message_id=raw["id"],
        attachments_payload=raw_attachments,
    )

    msg_rows = [obj for obj in session._added if isinstance(obj, ConversationMessage)]
    att_rows = [obj for obj in session._added if isinstance(obj, MessageAttachment)]

    assert len(msg_rows) == 1, "ConversationMessage should be created for text"
    assert len(att_rows) == 0, "No attachments expected for text-only message"
    assert msg_rows[0].content == "Hola"


# ---------------------------------------------------------------------------
# Scenario 7.3 — synthetic 2-attachment payload: positions 0 and 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_attachment_positions_are_sequential():
    """Scenario 7.3: 2 attachments → positions 0, 1 preserved in order."""
    from api.routes.chatwoot import upsert_conversation_history
    from database.models import ConversationMessage, MessageAttachment

    raw = _load_fixture("incoming_multi_attachment.json")
    payload = _build_payload(raw)

    session = _make_session()
    msg_row_id = uuid4()

    original_add = session.add.side_effect

    def _add_with_id(obj):
        if isinstance(obj, ConversationMessage):
            obj.id = msg_row_id
        original_add(obj)

    session.add.side_effect = _add_with_id

    raw_attachments = [att.model_dump() for att in payload.attachments]

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="",
        chatwoot_message_id=raw["id"],
        attachments_payload=raw_attachments,
    )

    att_rows = [obj for obj in session._added if isinstance(obj, MessageAttachment)]
    assert len(att_rows) == 2
    positions = sorted(r.position for r in att_rows)
    assert positions == [0, 1]


# ---------------------------------------------------------------------------
# Scenario 7.4 — synthetic attachment without data_url: 0 persisted, no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attachment_without_data_url_skipped():
    """Scenario 7.4: attachment dict missing data_url → 0 rows, no exception."""
    from api.routes.chatwoot import upsert_conversation_history
    from database.models import MessageAttachment

    raw = _load_fixture("incoming_image.json")
    payload = _build_payload(raw)

    # Corrupt the attachment so data_url is absent
    bad_attachments = [{"id": 99, "file_type": "image"}]

    session = _make_session()

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="",
        chatwoot_message_id=raw["id"],
        attachments_payload=bad_attachments,
    )

    att_rows = [obj for obj in session._added if isinstance(obj, MessageAttachment)]
    assert len(att_rows) == 0


# ---------------------------------------------------------------------------
# Scenario: content=null + attachments → message persisted (content='')
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_null_with_attachments_persists_message_with_empty_content():
    """Attachment-only message (content=null) → ConversationMessage with content=''."""
    from api.routes.chatwoot import upsert_conversation_history
    from database.models import ConversationMessage, MessageAttachment

    raw = _load_fixture("incoming_image.json")
    payload = _build_payload(raw)

    session = _make_session()

    msg_row_id = uuid4()
    original_add = session.add.side_effect

    def _add_with_id(obj):
        if isinstance(obj, ConversationMessage):
            obj.id = msg_row_id
        original_add(obj)

    session.add.side_effect = _add_with_id

    # Simulate what the webhook handler does: message_text="" when content is null
    raw_attachments = [att.model_dump() for att in payload.attachments]

    await upsert_conversation_history(
        session=session,
        payload=payload,
        message_text="",  # null content → empty string
        chatwoot_message_id=raw["id"],
        attachments_payload=raw_attachments,
    )

    msg_rows = [obj for obj in session._added if isinstance(obj, ConversationMessage)]
    att_rows = [obj for obj in session._added if isinstance(obj, MessageAttachment)]

    assert len(msg_rows) == 1, "Message row must be created even when content is empty"
    assert msg_rows[0].content == ""
    assert len(att_rows) == 1, "Attachment row must be created"


# ---------------------------------------------------------------------------
# Regression: ORM model has attachments relationship + MessageAttachment class exists
# ---------------------------------------------------------------------------


def test_message_attachment_orm_class_exists():
    """MessageAttachment ORM class is importable and has expected columns."""
    from sqlalchemy.inspection import inspect as sa_inspect

    from database.models import MessageAttachment

    mapper = sa_inspect(MessageAttachment)
    col_names = {col.key for col in mapper.mapper.column_attrs}

    assert "file_type" in col_names
    assert "url" in col_names
    assert "thumb_url" in col_names
    assert "size_bytes" in col_names
    assert "position" in col_names
    assert "message_id" in col_names


def test_conversation_message_has_attachments_relationship():
    """ConversationMessage has 'attachments' relationship back to MessageAttachment."""
    from sqlalchemy.inspection import inspect as sa_inspect

    from database.models import ConversationMessage

    mapper = sa_inspect(ConversationMessage)
    rel_names = {rel.key for rel in mapper.mapper.relationships}
    assert "attachments" in rel_names
