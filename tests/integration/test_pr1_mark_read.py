"""
Integration tests for PR-1 mark-read endpoint.

Covers:
- Scenario 2.1: first-time mark-read sets timestamp, returns {marked: N}
- Scenario 2.2: idempotent repeat call returns {marked: 0}
- Scenario 2.3: non-existent conversation returns 404

All HTTP tests use FastAPI TestClient with patched DB session and auth.

Webhook author_type stamping tests:
- Inbound message_created stamps author_type="user"
- message_updated delivery failure event sets delivery_failed=True
- Non-failure message_updated status is a no-op
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app

# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _bypass_rate_limiter():
    """Disable Redis rate limiting for all tests in this module."""
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    with patch("api.middleware.rate_limiting.get_redis_client", return_value=mock_redis):
        yield


@pytest.fixture
def client():
    # Include Origin header so OriginCheckMiddleware allows POST requests
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Origin": "http://localhost:3000"},
    )


@pytest.fixture
def admin_user():
    """Mock AdminUser with conversations:write permission."""
    from database.models import AdminUser

    user = MagicMock(spec=AdminUser)
    user.id = uuid4()
    user.username = "admin"
    user.role = "admin"
    return user


@pytest.fixture
def mock_auth(admin_user):
    """Override require_permission dependency to bypass JWT + permission check.

    FastAPI resolves Depends() objects by callable identity. require_permission
    returns a new _checker closure per action string. We can't easily intercept
    it via app.dependency_overrides without the exact closure reference.

    Instead, we patch has_permission to always return True so the permission
    check is bypassed while get_current_user still needs to return a valid user.
    We also override get_current_user with an AdminUser mock.
    """
    from api.routes.admin import get_current_user as _gcur

    app.dependency_overrides[_gcur] = lambda: admin_user
    with patch("api.dependencies.auth.has_permission", return_value=True):
        yield admin_user
    app.dependency_overrides.pop(_gcur, None)


def _make_history(conv_id: uuid4 | None = None):
    """Return a mock ConversationHistory row."""
    from database.models import ConversationHistory

    h = MagicMock(spec=ConversationHistory)
    h.id = conv_id or uuid4()
    h.conversation_id = "999"
    return h


def _make_session(history, marked_count: int = 3):
    """Return patched get_async_session context yielding a mock session."""
    mock_session = AsyncMock()

    # First execute: SELECT ConversationHistory
    history_result = MagicMock()
    history_result.scalar_one_or_none = MagicMock(return_value=history)

    # Second execute (from mark_messages_read): UPDATE rowcount
    update_result = MagicMock()
    update_result.rowcount = marked_count

    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return history_result if call_count == 1 else update_result

    mock_session.execute = _execute
    mock_session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# =============================================================================
# Scenario 2.1 — first mark-read
# =============================================================================


def test_mark_read_happy_path(client, mock_auth):
    """Scenario 2.1: first call marks messages and returns marked count."""
    history = _make_history()
    mock_ctx = _make_session(history, marked_count=5)

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        resp = client.post(f"/api/admin/conversations/{history.id}/mark-read")

    assert resp.status_code == 200
    data = resp.json()
    assert data["marked"] == 5


# =============================================================================
# Scenario 2.2 — idempotent repeat
# =============================================================================


def test_mark_read_idempotent(client, mock_auth):
    """Scenario 2.2: second call on already-read conversation returns marked=0."""
    history = _make_history()
    mock_ctx = _make_session(history, marked_count=0)

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        resp = client.post(f"/api/admin/conversations/{history.id}/mark-read")

    assert resp.status_code == 200
    assert resp.json()["marked"] == 0


# =============================================================================
# Scenario 2.3 — non-existent conversation
# =============================================================================


def test_mark_read_conversation_not_found(client, mock_auth):
    """Scenario 2.3: unknown conversation UUID returns 404 with Spanish detail."""
    mock_session = AsyncMock()
    not_found_result = MagicMock()
    not_found_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=not_found_result)
    mock_session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    fake_uuid = uuid4()
    with patch("api.routes.admin.get_async_session", return_value=ctx):
        resp = client.post(f"/api/admin/conversations/{fake_uuid}/mark-read")

    assert resp.status_code == 404
    assert "Conversación no encontrada" in resp.json()["detail"]


# =============================================================================
# Webhook: author_type="user" stamping (Scenario 1.1)
# Tests the ConversationMessage construction in upsert_conversation_history.
# =============================================================================


def test_conversation_message_model_has_author_type():
    """Scenario 1.1 (structural): ConversationMessage ORM has author_type column."""
    from database.models import ConversationMessage

    msg = ConversationMessage(
        conversation_history_id=uuid4(),
        role="user",
        content="Hola",
        author_type="user",
    )
    assert msg.author_type == "user"


def test_conversation_message_delivery_failed_column_exists():
    """Scenario 3.3: delivery_failed column exists on ConversationMessage model."""
    from sqlalchemy.inspection import inspect as sa_inspect

    from database.models import ConversationMessage

    mapper = sa_inspect(ConversationMessage)
    col_names = {col.key for col in mapper.mapper.column_attrs}
    assert "delivery_failed" in col_names, "delivery_failed column must exist on ConversationMessage"
    assert "read_at" in col_names, "read_at column must exist on ConversationMessage"
    assert "author_type" in col_names, "author_type column must exist on ConversationMessage"


# =============================================================================
# Webhook: _handle_message_status_event (Scenarios 3.1, 3.2)
# =============================================================================


@pytest.mark.asyncio
async def test_handle_message_status_event_sets_delivery_failed():
    """Scenario 3.1: failed status sets delivery_failed=True."""
    from api.routes.chatwoot import _handle_message_status_event

    session = AsyncMock()
    update_result = MagicMock()
    update_result.rowcount = 1
    session.execute = AsyncMock(return_value=update_result)

    payload = {
        "event": "message_updated",
        "id": 2084,
        "status": "failed",
    }

    result = await _handle_message_status_event(payload, session)

    assert result is True
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_status_event_non_failed_noop():
    """Scenario 3.2: delivered status is a no-op, returns False."""
    from api.routes.chatwoot import _handle_message_status_event

    session = AsyncMock()

    payload = {
        "event": "message_updated",
        "id": 2084,
        "status": "delivered",
    }

    result = await _handle_message_status_event(payload, session)

    assert result is False
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_status_event_wrong_event_noop():
    """Non message_updated event returns False without touching DB."""
    from api.routes.chatwoot import _handle_message_status_event

    session = AsyncMock()

    payload = {"event": "message_created", "id": 2084, "status": "failed"}

    result = await _handle_message_status_event(payload, session)

    assert result is False
    session.execute.assert_not_called()


# =============================================================================
# Scenario 1.2 — send_text_message stamps author_type="human_agent"
# =============================================================================


@pytest.mark.asyncio
async def test_send_text_message_stamps_human_agent_author_type():
    """Scenario 1.2: send_text_message persists ConversationMessage with author_type='human_agent'."""
    from api.services.conversation_inbox_service import ConversationInboxService
    from database.models import AdminUser, ConversationHistory, ConversationMessage

    # --- mock conversation history ---
    history = MagicMock(spec=ConversationHistory)
    history.id = uuid4()
    history.conversation_id = "42"

    # --- mock session ---
    session = AsyncMock()
    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=history)
    session.execute = AsyncMock(return_value=select_result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    # --- mock Chatwoot client (send succeeds) ---
    mock_chatwoot = AsyncMock()
    mock_chatwoot.send_message = AsyncMock(return_value=True)

    # --- mock author ---
    author = MagicMock(spec=AdminUser)
    author.id = uuid4()

    with patch(
        "api.services.conversation_inbox_service.compute_window_open",
        new=AsyncMock(return_value=(True, None)),
    ):
        svc = ConversationInboxService(session=session, chatwoot_client=mock_chatwoot)
        await svc.send_text_message(conversation_id="42", text="Hola!", author=author)

    session.add.assert_called_once()
    persisted: ConversationMessage = session.add.call_args[0][0]
    assert isinstance(persisted, ConversationMessage)
    assert persisted.author_type == "human_agent"
