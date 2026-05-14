"""
Integration tests for PR-2 conversation notes CRUD endpoints.

Covers Scenarios 4.1–4.4 from the spec:
  4.1 Create a note → 201 + note shape
  4.2 List notes for a conversation → 200, ordered
  4.3 Delete a note → 204, note absent from subsequent GET
  4.4 Note with empty content rejected → 422 (or 400/422)

Auth pattern (W4 pattern from PR-1):
  - TestClient with Origin: http://localhost:3000 header
  - patch("api.dependencies.auth.has_permission", return_value=True)
  - app.dependency_overrides[get_current_user] = lambda: admin_user
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _bypass_rate_limiter():
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    with patch("api.middleware.rate_limiting.get_redis_client", return_value=mock_redis):
        yield


@pytest.fixture
def admin_user():
    from database.models import AdminUser

    user = MagicMock(spec=AdminUser)
    user.id = uuid4()
    user.username = "admin"
    user.role = "admin"
    user.display_name = "Admin"
    return user


@pytest.fixture
def mock_auth(admin_user):
    from api.routes.admin import get_current_user as _gcur

    app.dependency_overrides[_gcur] = lambda: admin_user
    with patch("api.dependencies.auth.has_permission", return_value=True):
        yield admin_user
    app.dependency_overrides.pop(_gcur, None)


@pytest.fixture
def client():
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Origin": "http://localhost:3000"},
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_note_dict(content="Alergia al amoniaco", author_name="Admin"):
    return {
        "id": str(uuid4()),
        "content": content,
        "author_user_id": str(uuid4()),
        "author_name": author_name,
        "created_at": "2026-01-01T10:00:00+00:00",
        "updated_at": "2026-01-01T10:00:00+00:00",
    }


# ─── Scenario 4.1: Create a note ──────────────────────────────────────────────


def test_create_note_returns_201(client, mock_auth):
    """Scenario 4.1: POST /notes returns 201 with note body."""
    conv_id = str(uuid4())
    note_dict = _make_note_dict()

    with patch(
        "api.services.conversation_notes_service.create_note",
        AsyncMock(return_value=note_dict),
    ):
        resp = client.post(
            f"/api/admin/conversations/{conv_id}/notes",
            json={"content": "Alergia al amoniaco"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == note_dict["content"]
    assert "id" in data
    assert "author_name" in data
    assert "created_at" in data


# ─── Scenario 4.2: List notes ─────────────────────────────────────────────────


def test_list_notes_returns_200_with_items(client, mock_auth):
    """Scenario 4.2: GET /notes returns 200 with ordered array (created_at DESC)."""
    from database.models import ConversationHistory

    conv_id = str(uuid4())
    # Oldest note first in terms of timestamps, but service returns DESC so newest first.
    older_note = _make_note_dict("Primera nota (más antigua)")
    older_note["created_at"] = "2026-01-01T08:00:00+00:00"
    newer_note = _make_note_dict("Segunda nota (más reciente)")
    newer_note["created_at"] = "2026-01-01T10:00:00+00:00"
    # list_notes returns DESC order: newest first → [newer_note, older_note]
    notes_desc = [newer_note, older_note]

    mock_conv = MagicMock(spec=ConversationHistory)
    mock_conv.id = conv_id

    with (
        patch(
            "api.services.conversation_notes_service.list_notes",
            AsyncMock(return_value=notes_desc),
        ),
        patch("api.routes.admin.get_async_session") as mock_session_ctx,
    ):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_conv))
        )
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = client.get(f"/api/admin/conversations/{conv_id}/notes")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 2
    # Ordering assertion: newest note (T=10:00) must appear before older note (T=08:00)
    assert data["items"][0]["created_at"] > data["items"][1]["created_at"], (
        "Notes must be ordered by created_at DESC (newest first)"
    )


# ─── Scenario 4.3: Delete a note ──────────────────────────────────────────────


def test_delete_note_returns_204(client, mock_auth):
    """Scenario 4.3: DELETE /notes/{note_id} returns 204."""
    note_id = str(uuid4())

    with patch(
        "api.services.conversation_notes_service.delete_note",
        AsyncMock(return_value=True),
    ):
        with patch("api.routes.admin.get_async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.delete(f"/api/admin/conversations/notes/{note_id}")

    assert resp.status_code == 204


# ─── Scenario 4.4: Empty content rejected ─────────────────────────────────────


def test_create_note_with_empty_content_returns_4xx(client, mock_auth):
    """Scenario 4.4: Empty content → 422 (Pydantic validation) or 422 from service."""
    conv_id = str(uuid4())

    # Pydantic min_length=1 rejects empty string at validation layer → 422
    resp = client.post(
        f"/api/admin/conversations/{conv_id}/notes",
        json={"content": ""},
    )
    assert resp.status_code == 422


def test_create_note_with_whitespace_only_returns_422(client, mock_auth):
    """Whitespace-only content (passes Pydantic min_length but rejected by service)."""
    conv_id = str(uuid4())

    with patch(
        "api.services.conversation_notes_service.create_note",
        AsyncMock(side_effect=ValueError("El contenido de la nota no puede estar vacío.")),
    ):
        with patch("api.routes.admin.get_async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.post(
                f"/api/admin/conversations/{conv_id}/notes",
                json={"content": "   "},
            )

    assert resp.status_code == 422
    assert "vacío" in resp.json().get("detail", "")


# ─── 404 for non-existent conversation ────────────────────────────────────────


def test_list_notes_returns_404_for_unknown_conversation(client, mock_auth):
    conv_id = str(uuid4())

    with patch("api.routes.admin.get_async_session") as mock_session_ctx:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        resp = client.get(f"/api/admin/conversations/{conv_id}/notes")

    assert resp.status_code == 404
    assert "encontrada" in resp.json().get("detail", "").lower()
