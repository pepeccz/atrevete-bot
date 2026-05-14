"""
Unit tests for the ``_persist_attachments`` webhook helper (PR-3a).

Tests verify:
- Items without data_url are skipped (no crash, warning logged)
- Fields map correctly when all fields are present
- Missing optional fields default to None
- Position is assigned in input order (0-indexed)
- Empty / None list → 0 rows persisted, no crash
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# =============================================================================
# Helper — build a minimal session mock that captures session.add() calls
# =============================================================================


def _make_session():
    """Return a mock AsyncSession that records add() calls."""
    session = AsyncMock()
    session._added = []

    def _add(obj):
        session._added.append(obj)

    session.add = MagicMock(side_effect=_add)
    return session


# =============================================================================
# T3a.5/T3a.6 — unit tests for _persist_attachments
# =============================================================================


@pytest.mark.asyncio
async def test_persist_attachments_skips_item_without_data_url():
    """Attachment entry missing data_url is skipped; no crash; 0 rows added."""
    from api.routes.chatwoot import _persist_attachments

    session = _make_session()
    attachments = [{"id": 1, "file_type": "image"}]  # no data_url

    count = await _persist_attachments(
        message_id=uuid4(),
        attachments_payload=attachments,
        session=session,
    )

    assert count == 0
    assert session._added == []


@pytest.mark.asyncio
async def test_persist_attachments_maps_fields_correctly():
    """All present fields are mapped to the correct ORM attributes."""
    from api.routes.chatwoot import _persist_attachments

    session = _make_session()
    msg_id = uuid4()
    attachments = [
        {
            "id": 1,
            "file_type": "image",
            "data_url": "https://example.com/img.jpg",
            "thumb_url": "https://example.com/thumb.jpg",
            "file_size": 232934,
            "width": 1280,
            "height": 720,
            "content_type": "image/jpeg",
        }
    ]

    count = await _persist_attachments(
        message_id=msg_id,
        attachments_payload=attachments,
        session=session,
    )

    assert count == 1
    assert len(session._added) == 1
    row = session._added[0]
    assert row.message_id == msg_id
    assert row.file_type == "image"
    assert row.url == "https://example.com/img.jpg"
    assert row.thumb_url == "https://example.com/thumb.jpg"
    assert row.size_bytes == 232934
    assert row.width == 1280
    assert row.height == 720
    assert row.content_type == "image/jpeg"
    assert row.position == 0


@pytest.mark.asyncio
async def test_persist_attachments_defaults_missing_optional_fields_to_none():
    """Optional fields (thumb_url, width, height, filename, etc.) default to None."""
    from api.routes.chatwoot import _persist_attachments

    session = _make_session()
    attachments = [
        {
            "id": 5,
            "file_type": "file",
            "data_url": "https://example.com/doc.pdf",
        }
    ]

    count = await _persist_attachments(
        message_id=uuid4(),
        attachments_payload=attachments,
        session=session,
    )

    assert count == 1
    row = session._added[0]
    assert row.thumb_url is None
    assert row.width is None
    assert row.height is None
    assert row.filename is None
    assert row.size_bytes is None
    assert row.content_type is None


@pytest.mark.asyncio
async def test_persist_attachments_position_assigned_in_input_order():
    """Position is the enumerate index of the input list (0, 1, 2)."""
    from api.routes.chatwoot import _persist_attachments

    session = _make_session()
    attachments = [
        {"id": 1, "file_type": "image", "data_url": "https://example.com/a.jpg"},
        {"id": 2, "file_type": "image", "data_url": "https://example.com/b.jpg"},
        {"id": 3, "file_type": "image", "data_url": "https://example.com/c.jpg"},
    ]

    count = await _persist_attachments(
        message_id=uuid4(),
        attachments_payload=attachments,
        session=session,
    )

    assert count == 3
    positions = [row.position for row in session._added]
    assert positions == [0, 1, 2]


@pytest.mark.asyncio
async def test_persist_attachments_empty_list_returns_zero():
    """Empty list → 0 rows persisted, no exception."""
    from api.routes.chatwoot import _persist_attachments

    session = _make_session()

    count = await _persist_attachments(
        message_id=uuid4(),
        attachments_payload=[],
        session=session,
    )

    assert count == 0
    assert session._added == []


@pytest.mark.asyncio
async def test_persist_attachments_none_payload_returns_zero():
    """None payload → 0 rows persisted, no exception."""
    from api.routes.chatwoot import _persist_attachments

    session = _make_session()

    count = await _persist_attachments(
        message_id=uuid4(),
        attachments_payload=None,
        session=session,
    )

    assert count == 0


@pytest.mark.asyncio
async def test_persist_attachments_partial_skip_keeps_valid_items():
    """Mixed list: item without data_url is skipped, valid items are persisted."""
    from api.routes.chatwoot import _persist_attachments

    session = _make_session()
    attachments = [
        {"id": 1, "file_type": "image"},  # no data_url — skip
        {"id": 2, "file_type": "image", "data_url": "https://example.com/img.jpg"},
        {"id": 3, "file_type": "file"},   # no data_url — skip
    ]

    count = await _persist_attachments(
        message_id=uuid4(),
        attachments_payload=attachments,
        session=session,
    )

    assert count == 1
    assert session._added[0].url == "https://example.com/img.jpg"
    # Position reflects enumerate order in the input, not count of valid items
    assert session._added[0].position == 1


@pytest.mark.asyncio
async def test_persist_attachments_file_type_defaults_to_file_when_missing():
    """file_type defaults to 'file' when the key is absent."""
    from api.routes.chatwoot import _persist_attachments

    session = _make_session()
    attachments = [{"data_url": "https://example.com/x"}]  # no file_type

    count = await _persist_attachments(
        message_id=uuid4(),
        attachments_payload=attachments,
        session=session,
    )

    assert count == 1
    assert session._added[0].file_type == "file"
