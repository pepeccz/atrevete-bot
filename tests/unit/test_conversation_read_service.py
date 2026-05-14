"""Unit tests for conversation_read_service.mark_messages_read.

Covers:
- Happy path: marks unread messages and returns count (Scenario 2.1)
- Idempotent repeat: already-read messages return 0 (Scenario 2.2)
- up_to_message_id bound: only messages up to cutoff are updated
- Invalid up_to_message_id: raises ValueError
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_msg(
    created_at: datetime | None = None,
    read_at: datetime | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.id = uuid4()
    msg.created_at = created_at or datetime.now(tz=UTC)
    msg.read_at = read_at
    return msg


def _make_update_result(rowcount: int) -> MagicMock:
    r = MagicMock()
    r.rowcount = rowcount
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_messages_read_returns_count():
    """Scenario 2.1: marks unread messages and returns affected row count."""
    from api.services.conversation_read_service import mark_messages_read

    session = AsyncMock()
    # execute() for the update stmt returns a result with rowcount=3
    session.execute = AsyncMock(return_value=_make_update_result(3))

    conv_id = uuid4()
    count = await mark_messages_read(session, conversation_history_id=conv_id)

    assert count == 3
    # execute must be called (the UPDATE stmt)
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_mark_messages_read_idempotent_returns_zero():
    """Scenario 2.2: all messages already read — rowcount 0, no error."""
    from api.services.conversation_read_service import mark_messages_read

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_update_result(0))

    count = await mark_messages_read(session, conversation_history_id=uuid4())

    assert count == 0


@pytest.mark.asyncio
async def test_mark_messages_read_with_up_to_message_id():
    """up_to_message_id limits the update to messages up to that created_at."""
    from api.services.conversation_read_service import mark_messages_read

    session = AsyncMock()
    msg_id = uuid4()
    cutoff_ts = datetime.now(tz=UTC) - timedelta(hours=1)

    # First call: SELECT to resolve cutoff timestamp
    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=cutoff_ts)
    # Second call: UPDATE
    update_result = _make_update_result(2)

    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return select_result if call_count == 1 else update_result

    session.execute = _execute

    count = await mark_messages_read(
        session,
        conversation_history_id=uuid4(),
        up_to_message_id=msg_id,
    )

    assert count == 2
    assert call_count == 2


@pytest.mark.asyncio
async def test_mark_messages_read_invalid_up_to_raises():
    """up_to_message_id not found in conversation raises ValueError."""
    from api.services.conversation_read_service import mark_messages_read

    session = AsyncMock()
    # SELECT returns None (message not found in this conversation)
    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=select_result)

    with pytest.raises(ValueError, match="not found in conversation"):
        await mark_messages_read(
            session,
            conversation_history_id=uuid4(),
            up_to_message_id=uuid4(),
        )
