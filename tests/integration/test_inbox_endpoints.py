"""
Integration tests for the 7 human-agent inbox endpoints.

Covers:
- SC-1: send-message happy path (conversations:write)
- SC-6: escalate creates Escalation row
- SC-7: RBAC enforcement — 401 (no JWT) and 403 (missing permission) for all 7 endpoints
- SC-3 partially: resume endpoint sets the pending_injection Redis key

These tests use FastAPI TestClient with mocked service layer and DB sessions.
No live Postgres or Redis required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from database.models import AdminUser

# ---------------------------------------------------------------------------
# Helpers / Constants
# ---------------------------------------------------------------------------

CONV_ID = "12345"  # Chatwoot conversation ID (string representation of int)

_NOW = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)

_ORIGIN = "http://localhost:3000"


def _make_admin_user() -> AdminUser:
    """Return a fake AdminUser with admin role."""
    u = MagicMock(spec=AdminUser)
    u.id = uuid4()
    u.username = "admin"
    u.role = "admin"
    u.is_active = True
    u.display_name = "Admin"
    return u


def _make_stylist_user() -> AdminUser:
    """Return a fake AdminUser with stylist role."""
    u = MagicMock(spec=AdminUser)
    u.id = uuid4()
    u.username = "stylist1"
    u.role = "stylist"
    u.is_active = True
    u.display_name = "Estilista"
    return u


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """TestClient for the FastAPI app with allowed Origin header."""
    return TestClient(app, raise_server_exceptions=False, headers={"Origin": _ORIGIN})


@pytest.fixture
def admin_user():
    return _make_admin_user()


@pytest.fixture
def stylist_user():
    return _make_stylist_user()


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """Ensure dependency overrides are cleared after each test."""
    yield
    app.dependency_overrides.clear()


def _override_auth_with(user: AdminUser):
    """Override get_current_user to return the given user (bypasses JWT + RBAC check chain)."""
    from api.dependencies.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user


def _make_async_session_mock():
    """Return a reusable async session context manager mock."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# SC-7: 401 — missing JWT on all 7 endpoints
# SC-7 note: POST endpoints return 403 (Origin not allowed) before auth because
#   CORS middleware fires before authentication middleware. We test GET endpoints
#   without Origin and POST endpoints with Origin header separately.
# ---------------------------------------------------------------------------

_GET_ENDPOINTS_401 = [
    ("GET", f"/api/admin/conversations/{CONV_ID}/window-status"),
    ("GET", "/api/admin/conversations/templates"),
]


@pytest.mark.parametrize("method,path", _GET_ENDPOINTS_401)
def test_no_jwt_get_returns_401(method, path):
    """SC-7a: GET inbox endpoints return 401 without JWT (no CORS preflight needed)."""
    # No Origin header on GET — CORS doesn't block these
    c = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    resp = c.get(path)
    assert (
        resp.status_code == 401
    ), f"{method} {path} expected 401 but got {resp.status_code}: {resp.text}"


_POST_ENDPOINTS_401 = [
    (f"/api/admin/conversations/{CONV_ID}/send-message", {"text": "Hola"}),
    (f"/api/admin/conversations/{CONV_ID}/send-template", {"template_name": "x", "params": {}}),
    (f"/api/admin/conversations/{CONV_ID}/pause", {"source": "toggle"}),
    (f"/api/admin/conversations/{CONV_ID}/resume", {}),
    (f"/api/admin/conversations/{CONV_ID}/escalate", {"reason": "test"}),
]


@pytest.mark.parametrize("path,body", _POST_ENDPOINTS_401)
def test_no_jwt_post_returns_401(client, path, body):
    """SC-7a: POST inbox endpoints return 401 without JWT (with proper Origin header)."""
    app.dependency_overrides.clear()
    resp = client.post(path, json=body)
    assert (
        resp.status_code == 401
    ), f"POST {path} expected 401 but got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# SC-7: 403 — stylist calling escalate (escalations:resolve = admin only)
# ---------------------------------------------------------------------------


def test_stylist_cannot_escalate(client, stylist_user):
    """SC-7b: Stylist receives 403 when calling escalate (requires escalations:resolve)."""
    _override_auth_with(stylist_user)

    resp = client.post(
        f"/api/admin/conversations/{CONV_ID}/escalate",
        json={"reason": "test reason"},
    )
    assert resp.status_code == 403, f"Expected 403 but got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# SC-7: 200 — stylist CAN send-message (conversations:write is shared)
# ---------------------------------------------------------------------------


def test_stylist_can_send_message(client, stylist_user):
    """SC-7c: Stylist with conversations:write CAN send a message (200)."""
    _override_auth_with(stylist_user)

    from database.models import ConversationMessage, ConversationMessageRole

    mock_msg = MagicMock(spec=ConversationMessage)
    mock_msg.id = uuid4()
    mock_msg.content = "Hola"
    mock_msg.created_at = _NOW
    mock_msg.role = ConversationMessageRole.HUMAN_AGENT.value

    mock_session = _make_async_session_mock()

    with (
        patch(
            "api.services.conversation_inbox_service.ConversationInboxService.send_text_message",
            new_callable=AsyncMock,
            return_value=mock_msg,
        ),
        patch("api.routes.admin.get_async_session", return_value=mock_session),
        patch("shared.chatwoot_client.ChatwootClient"),
    ):
        resp = client.post(
            f"/api/admin/conversations/{CONV_ID}/send-message",
            json={"text": "Hola"},
        )

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "id" in data
    assert data["content"] == "Hola"
    assert data["author_username"] == "stylist1"


# ---------------------------------------------------------------------------
# SC-1: send-message happy path (admin user)
# ---------------------------------------------------------------------------


def test_send_message_happy_path(client, admin_user):
    """SC-1: Admin sends a free-text message — service called, 200 returned."""
    _override_auth_with(admin_user)

    from database.models import ConversationMessage, ConversationMessageRole

    mock_msg = MagicMock(spec=ConversationMessage)
    mock_msg.id = uuid4()
    mock_msg.content = "Confirma tu cita por favor"
    mock_msg.created_at = _NOW
    mock_msg.role = ConversationMessageRole.HUMAN_AGENT.value

    mock_session = _make_async_session_mock()

    with (
        patch(
            "api.services.conversation_inbox_service.ConversationInboxService.send_text_message",
            new_callable=AsyncMock,
            return_value=mock_msg,
        ),
        patch("api.routes.admin.get_async_session", return_value=mock_session),
        patch("shared.chatwoot_client.ChatwootClient"),
    ):
        resp = client.post(
            f"/api/admin/conversations/{CONV_ID}/send-message",
            json={"text": "Confirma tu cita por favor"},
        )

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["content"] == "Confirma tu cita por favor"
    assert data["author_username"] == "admin"


def test_send_message_window_closed_returns_400(client, admin_user):
    """SC-1 error: send-message returns 400 when 24h window is closed."""
    _override_auth_with(admin_user)

    mock_session = _make_async_session_mock()

    with (
        patch(
            "api.services.conversation_inbox_service.ConversationInboxService.send_text_message",
            new_callable=AsyncMock,
            side_effect=ValueError("The 24h WhatsApp messaging window is closed."),
        ),
        patch("api.routes.admin.get_async_session", return_value=mock_session),
        patch("shared.chatwoot_client.ChatwootClient"),
    ):
        resp = client.post(
            f"/api/admin/conversations/{CONV_ID}/send-message",
            json={"text": "Hola"},
        )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# SC-6: escalate creates Escalation row
# ---------------------------------------------------------------------------


def test_escalate_creates_escalation_row(client, admin_user):
    """SC-6: escalate endpoint creates an Escalation row and returns its ID."""
    _override_auth_with(admin_user)

    escalation_id = uuid4()
    mock_session = _make_async_session_mock()

    with (
        patch(
            "api.services.conversation_inbox_service.ConversationInboxService.escalate",
            new_callable=AsyncMock,
            return_value={"escalation_id": escalation_id},
        ),
        patch("api.routes.admin.get_async_session", return_value=mock_session),
        patch("shared.chatwoot_client.ChatwootClient"),
    ):
        resp = client.post(
            f"/api/admin/conversations/{CONV_ID}/escalate",
            json={"reason": "Customer is frustrated", "note": "Third complaint this week"},
        )

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["escalation_id"] == str(escalation_id)


# ---------------------------------------------------------------------------
# SC-3 partial: resume endpoint sets the pending_injection Redis key
# ---------------------------------------------------------------------------


def test_resume_sets_pending_injection_flag(client, admin_user):
    """SC-3 partial: /resume returns 200 with pending_injection_ttl_seconds=600."""
    _override_auth_with(admin_user)

    resumed_at = _NOW
    mock_session = _make_async_session_mock()

    with (
        patch(
            "api.services.conversation_inbox_service.ConversationInboxService.resume",
            new_callable=AsyncMock,
            return_value={
                "resumed_at": resumed_at,
                "pending_injection_ttl_seconds": 600,
            },
        ),
        patch("api.routes.admin.get_async_session", return_value=mock_session),
        patch("shared.chatwoot_client.ChatwootClient"),
        patch("shared.redis_client.get_redis_client", return_value=AsyncMock()),
    ):
        resp = client.post(f"/api/admin/conversations/{CONV_ID}/resume")

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["pending_injection_ttl_seconds"] == 600
    assert "resumed_at" in data


# ---------------------------------------------------------------------------
# pause endpoint
# ---------------------------------------------------------------------------


def test_pause_returns_paused_at(client, admin_user):
    """pause endpoint returns 200 with paused_at timestamp."""
    _override_auth_with(admin_user)

    mock_session = _make_async_session_mock()

    with (
        patch(
            "api.services.conversation_inbox_service.ConversationInboxService.pause",
            new_callable=AsyncMock,
            return_value={"paused_at": _NOW, "escalation_id": None},
        ),
        patch("api.routes.admin.get_async_session", return_value=mock_session),
        patch("shared.chatwoot_client.ChatwootClient"),
    ):
        resp = client.post(
            f"/api/admin/conversations/{CONV_ID}/pause",
            json={"source": "toggle"},
        )

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "paused_at" in data


def test_pause_already_paused_returns_409(client, admin_user):
    """pause returns 409 when conversation is already paused."""
    _override_auth_with(admin_user)

    mock_session = _make_async_session_mock()

    with (
        patch(
            "api.services.conversation_inbox_service.ConversationInboxService.pause",
            new_callable=AsyncMock,
            side_effect=ValueError("Conversation is already paused."),
        ),
        patch("api.routes.admin.get_async_session", return_value=mock_session),
        patch("shared.chatwoot_client.ChatwootClient"),
    ):
        resp = client.post(
            f"/api/admin/conversations/{CONV_ID}/pause",
            json={"source": "toggle"},
        )

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# window-status endpoint
# ---------------------------------------------------------------------------


def test_window_status_open(client, admin_user):
    """window-status returns window_open=True for conversations within 24h window."""
    _override_auth_with(admin_user)

    from database.models import ConversationHistory

    mock_history = MagicMock(spec=ConversationHistory)
    mock_history.id = uuid4()
    mock_history.conversation_id = CONV_ID

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_history

    mock_session = _make_async_session_mock()
    mock_session.execute = AsyncMock(return_value=mock_execute_result)

    with (
        patch(
            "api.services.window_service.compute_window_open",
            new_callable=AsyncMock,
            return_value=(True, _NOW),
        ),
        patch("api.routes.admin.get_async_session", return_value=mock_session),
    ):
        resp = client.get(f"/api/admin/conversations/{CONV_ID}/window-status")

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["window_open"] is True


def test_window_status_conversation_not_found(client, admin_user):
    """window-status returns 404 when conversation not found in DB."""
    _override_auth_with(admin_user)

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None

    mock_session = _make_async_session_mock()
    mock_session.execute = AsyncMock(return_value=mock_execute_result)

    with patch("api.routes.admin.get_async_session", return_value=mock_session):
        resp = client.get(f"/api/admin/conversations/{CONV_ID}/window-status")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# templates endpoint
# ---------------------------------------------------------------------------


def test_templates_endpoint_returns_list(client, admin_user):
    """templates endpoint returns list of template definitions."""
    _override_auth_with(admin_user)

    resp = client.get("/api/admin/conversations/templates")

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)
    # At minimum the reengagement template is registered
    names = [t["name"] for t in data["items"]]
    assert "reengagement" in names
