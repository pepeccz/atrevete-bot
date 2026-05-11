"""Regression tests: inbox service must call Chatwoot with the int id from
the ConversationHistory row, NOT with the UUID path param the admin panel sends.

Bug history:
  PR-2 used `int(conversation_id)` directly. The admin panel passes
  ConversationHistory.id (UUID), so `int()` raised ValueError → mapped to 409
  by the pause endpoint. Hotfix: every Chatwoot call now uses
  `int(history.conversation_id)`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from api.services.conversation_inbox_service import ConversationInboxService


def _fake_history(chatwoot_int_id: str = "42"):
    """Build a fake ConversationHistory with the given Chatwoot string id."""
    h = MagicMock()
    h.id = uuid4()
    h.conversation_id = chatwoot_int_id
    h.paused_at = None
    h.resumed_at = None
    h.customer_id = None
    h.metadata_ = {}
    return h


@pytest.mark.asyncio
async def test_pause_uses_history_chatwoot_id_for_api_call():
    """pause() must call Chatwoot with int(history.conversation_id), not the path param."""
    chatwoot = AsyncMock()
    chatwoot.update_conversation_attributes = AsyncMock(return_value=None)
    session = AsyncMock()
    session.commit = AsyncMock()

    service = ConversationInboxService(session=session, chatwoot_client=chatwoot)
    fake_hist = _fake_history(chatwoot_int_id="42")
    admin = MagicMock(id=uuid4(), username="admin", role="admin")

    with patch.object(service, "_get_history", return_value=fake_hist):
        result = await service.pause(conversation_id=str(uuid4()), source="toggle", author=admin)

    chatwoot.update_conversation_attributes.assert_awaited_once()
    call_kwargs = chatwoot.update_conversation_attributes.await_args.kwargs
    assert call_kwargs["conversation_id"] == 42
    assert isinstance(call_kwargs["conversation_id"], int)
    assert call_kwargs["attributes"] == {"atencion_automatica": False}
    assert "paused_at" in result


@pytest.mark.asyncio
async def test_resume_sets_redis_key_with_chatwoot_id():
    """resume() must key the pending_injection Redis flag by Chatwoot int, not UUID."""
    chatwoot = AsyncMock()
    chatwoot.update_conversation_attributes = AsyncMock(return_value=None)
    session = AsyncMock()
    session.commit = AsyncMock()

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=empty_result)

    redis_client = AsyncMock()
    redis_client.set = AsyncMock()

    service = ConversationInboxService(session=session, chatwoot_client=chatwoot)
    fake_hist = _fake_history(chatwoot_int_id="42")
    fake_hist.paused_at = datetime.now(tz=UTC)
    admin = MagicMock(id=uuid4(), username="admin", role="admin")

    with patch.object(service, "_get_history", return_value=fake_hist):
        await service.resume(conversation_id=str(uuid4()), author=admin, redis_client=redis_client)

    redis_client.set.assert_awaited_once()
    key_arg = redis_client.set.await_args.args[0]
    assert key_arg == "pending_injection:v2:42"


@pytest.mark.asyncio
async def test_uuid_path_param_does_not_blow_up_int_call():
    """Passing a UUID as path param must NOT raise ValueError on int() conversion.

    Literal regression test for the 409 bug.
    """
    chatwoot = AsyncMock()
    chatwoot.update_conversation_attributes = AsyncMock(return_value=None)
    session = AsyncMock()
    session.commit = AsyncMock()

    service = ConversationInboxService(session=session, chatwoot_client=chatwoot)
    fake_hist = _fake_history(chatwoot_int_id="8")
    admin = MagicMock(id=uuid4(), username="admin", role="admin")

    uuid_path_param = "ea72baff-1a69-4bb2-8800-a47eeeed7439"

    with patch.object(service, "_get_history", return_value=fake_hist):
        result = await service.pause(conversation_id=uuid_path_param, source="toggle", author=admin)

    assert chatwoot.update_conversation_attributes.await_args.kwargs["conversation_id"] == 8
    assert result["paused_at"] is not None
