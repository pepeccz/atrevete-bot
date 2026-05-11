"""Unit tests for ConversationInboxService._get_history tolerant lookup.

Regression test for the bug where inbox endpoints used Chatwoot string id
to find a ConversationHistory row, but the admin panel sent the UUID PK.
The fix accepts both formats.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from api.services.conversation_inbox_service import ConversationInboxService


def _stub_session(*scalar_results):
    """Build a session whose ``execute`` returns mock rows yielding the given scalars.

    Pass one element per expected ``execute`` call. Each is the value that
    ``.scalar_one_or_none()`` will return for that call.
    """
    session = AsyncMock()
    mocks = []
    for value in scalar_results:
        m = MagicMock()
        m.scalar_one_or_none.return_value = value
        mocks.append(m)
    session.execute = AsyncMock(side_effect=mocks)
    return session


@pytest.mark.asyncio
async def test_lookup_by_uuid_string_hits_first_query():
    """A valid UUID string queries by ConversationHistory.id and stops there."""
    fake_history = object()
    session = _stub_session(fake_history)  # one execute, returns hit
    service = ConversationInboxService(session=session, chatwoot_client=None)

    result = await service._get_history(str(uuid4()))

    assert result is fake_history
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_lookup_by_chatwoot_int_string_skips_uuid_query():
    """A non-UUID string only issues the string-column query."""
    fake_history = object()
    session = _stub_session(fake_history)  # one execute, returns hit
    service = ConversationInboxService(session=session, chatwoot_client=None)

    result = await service._get_history("12345")

    assert result is fake_history
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_lookup_uuid_miss_falls_back_to_string():
    """A valid UUID with no .id match still tries the conversation_id column."""
    fake_history = object()
    session = _stub_session(None, fake_history)  # UUID miss, then string hit
    service = ConversationInboxService(session=session, chatwoot_client=None)

    result = await service._get_history(str(uuid4()))

    assert result is fake_history
    assert session.execute.call_count == 2


@pytest.mark.asyncio
async def test_lookup_not_found_raises_value_error():
    """Neither lookup matches → ValueError 'not found'."""
    session = _stub_session(None, None)  # both misses for a valid UUID input
    service = ConversationInboxService(session=session, chatwoot_client=None)

    with pytest.raises(ValueError, match="not found"):
        await service._get_history(str(uuid4()))
