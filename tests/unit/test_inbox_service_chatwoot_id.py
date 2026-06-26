"""
Unit tests for ConversationInboxService pause/resume — DB-only SSOT (T-05/T-06).

After the T-06 rewrite:
- pause()  writes paused_at to DB; does NOT call update_conversation_attributes
- resume() writes resumed_at + clears paused_at in DB; does NOT call
  update_conversation_attributes; sets pending_injection Redis key
- Neither method raises RuntimeError (Chatwoot path removed)

Spec refs: R3-A, R3-B, R6-A, ADR-6 step 7
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from api.services.conversation_inbox_service import ConversationInboxService


def _fake_history(chatwoot_int_id: str = "42", paused_at: datetime | None = None):
    """Build a fake ConversationHistory."""
    h = MagicMock()
    h.id = uuid4()
    h.conversation_id = chatwoot_int_id
    h.paused_at = paused_at
    h.resumed_at = None
    h.customer_id = None
    h.metadata_ = {}
    return h


def _fake_admin():
    return MagicMock(id=uuid4(), username="admin", role="admin")


# ---------------------------------------------------------------------------
# T-05#1  pause() — DB only, no Chatwoot write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_sets_paused_at_in_db_no_chatwoot() -> None:
    """pause() sets history.paused_at to a UTC timestamp; never calls update_conversation_attributes."""
    chatwoot = AsyncMock()
    chatwoot.update_conversation_attributes = AsyncMock()

    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    service = ConversationInboxService(session=session, chatwoot_client=chatwoot)
    fake_hist = _fake_history()
    admin = _fake_admin()

    with patch.object(service, "_get_history", return_value=fake_hist):
        result = await service.pause(conversation_id=str(uuid4()), source="toggle", author=admin)

    # paused_at is set to a UTC datetime
    assert fake_hist.paused_at is not None
    assert isinstance(fake_hist.paused_at, datetime)
    assert fake_hist.paused_at.tzinfo is not None
    assert "paused_at" in result

    # Chatwoot NOT called
    chatwoot.update_conversation_attributes.assert_not_awaited()


@pytest.mark.asyncio
async def test_pause_does_not_raise_runtime_error() -> None:
    """pause() must never raise RuntimeError (Chatwoot path removed)."""
    chatwoot = AsyncMock()
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    service = ConversationInboxService(session=session, chatwoot_client=chatwoot)
    fake_hist = _fake_history()
    admin = _fake_admin()

    with patch.object(service, "_get_history", return_value=fake_hist):
        # Should complete without raising RuntimeError
        try:
            await service.pause(conversation_id=str(uuid4()), source="toggle", author=admin)
        except RuntimeError as exc:
            pytest.fail(f"pause() raised RuntimeError unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# T-05#2  resume() — DB only, Redis key set, no Chatwoot write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_sets_resumed_at_clears_paused_at_no_chatwoot() -> None:
    """resume() sets resumed_at, clears paused_at=None; never calls update_conversation_attributes."""
    chatwoot = AsyncMock()
    chatwoot.update_conversation_attributes = AsyncMock()

    now = datetime.now(tz=UTC)
    fake_hist = _fake_history(paused_at=now)

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=empty_result)
    session.commit = AsyncMock()

    redis_client = AsyncMock()
    redis_client.set = AsyncMock()

    service = ConversationInboxService(session=session, chatwoot_client=chatwoot)
    admin = _fake_admin()

    with patch.object(service, "_get_history", return_value=fake_hist):
        result = await service.resume(
            conversation_id=str(uuid4()), author=admin, redis_client=redis_client
        )

    # resumed_at is a UTC datetime
    assert fake_hist.resumed_at is not None
    assert isinstance(fake_hist.resumed_at, datetime)
    # paused_at cleared (ADR-3 / F7)
    assert fake_hist.paused_at is None
    assert "resumed_at" in result

    # Redis key set with TTL 600
    redis_client.set.assert_awaited_once()
    call_args = redis_client.set.call_args
    key = call_args.args[0] if call_args.args else call_args.kwargs.get("name")
    assert "pending_injection:v2:42" in key
    ttl = call_args.kwargs.get("ex") or (call_args.args[2] if len(call_args.args) > 2 else None)
    assert ttl == 600

    # Chatwoot NOT called
    chatwoot.update_conversation_attributes.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_does_not_raise_runtime_error() -> None:
    """resume() must never raise RuntimeError (Chatwoot path removed)."""
    chatwoot = AsyncMock()

    now = datetime.now(tz=UTC)
    fake_hist = _fake_history(paused_at=now)

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=empty_result)
    session.commit = AsyncMock()

    redis_client = AsyncMock()
    redis_client.set = AsyncMock()

    service = ConversationInboxService(session=session, chatwoot_client=chatwoot)
    admin = _fake_admin()

    with patch.object(service, "_get_history", return_value=fake_hist):
        try:
            await service.resume(
                conversation_id=str(uuid4()), author=admin, redis_client=redis_client
            )
        except RuntimeError as exc:
            pytest.fail(f"resume() raised RuntimeError unexpectedly: {exc}")
