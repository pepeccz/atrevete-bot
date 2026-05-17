"""
Integration tests for PR-2 sidebar aggregate endpoint.

Covers Scenarios 5.1–5.3 from the spec:
  5.1 Happy path — customer with notes + active escalation
  5.2 Customer with no notes or escalation
  5.3 Unknown conversation ID → 404

Auth pattern (W4 pattern from PR-1).
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


# ─── Scenario 5.1: Happy path ─────────────────────────────────────────────────


def test_sidebar_happy_path_returns_200_with_full_shape(client, mock_auth):
    """Scenario 5.1: customer + notes + active escalation."""
    conv_id = str(uuid4())
    sidebar_data = {
        "customer": {
            "id": str(uuid4()),
            "name": "María García",
            "phone": "+34 612 345 678",
            "customer_notes_count": 3,
        },
        "notes": [
            {
                "id": str(uuid4()),
                "content": "Alergia al amoniaco",
                "author_user_id": str(uuid4()),
                "author_name": "Admin",
                "created_at": "2026-01-01T10:00:00+00:00",
                "updated_at": "2026-01-01T10:00:00+00:00",
            }
        ],
        "active_escalation": {
            "id": str(uuid4()),
            "reason": "Cliente muy molesto",
            "triggered_at": "2026-01-01T09:00:00+00:00",
        },
    }

    with patch(
        "api.services.conversation_inbox_service.build_sidebar",
        AsyncMock(return_value=sidebar_data),
    ):
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get(f"/api/admin/conversations/{conv_id}/sidebar")

    assert resp.status_code == 200
    data = resp.json()
    assert data["customer"]["name"] == "María García"
    assert data["customer"]["customer_notes_count"] == 3
    assert len(data["notes"]) == 1
    assert data["active_escalation"]["reason"] == "Cliente muy molesto"


# ─── Scenario 5.2: No notes, no escalation ────────────────────────────────────


def test_sidebar_no_notes_no_escalation(client, mock_auth):
    """Scenario 5.2: customer present but no notes and no escalation."""
    conv_id = str(uuid4())
    sidebar_data = {
        "customer": {
            "id": str(uuid4()),
            "name": "Ana López",
            "phone": "+34 666 111 222",
            "customer_notes_count": 0,
        },
        "notes": [],
        "active_escalation": None,
    }

    with patch(
        "api.services.conversation_inbox_service.build_sidebar",
        AsyncMock(return_value=sidebar_data),
    ):
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get(f"/api/admin/conversations/{conv_id}/sidebar")

    assert resp.status_code == 200
    data = resp.json()
    assert data["customer"]["customer_notes_count"] == 0
    assert data["notes"] == []
    assert data["active_escalation"] is None


# ─── Scenario 5.3: Unknown conversation ───────────────────────────────────────


def test_sidebar_unknown_conversation_returns_404(client, mock_auth):
    """Scenario 5.3: unknown conversation_id → 404 with Spanish message."""
    conv_id = str(uuid4())

    with patch(
        "api.services.conversation_inbox_service.build_sidebar",
        AsyncMock(side_effect=LookupError("Conversación no encontrada.")),
    ):
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get(f"/api/admin/conversations/{conv_id}/sidebar")

    assert resp.status_code == 404
    assert "encontrada" in resp.json().get("detail", "").lower()


# ─── notes_count correctness ──────────────────────────────────────────────────


def test_sidebar_notes_count_reflects_all_customer_conversations(client, mock_auth):
    """Customer-wide notes count includes notes from other conversations."""
    conv_id = str(uuid4())
    sidebar_data = {
        "customer": {
            "id": str(uuid4()),
            "name": "Pepa",
            "phone": "+34 600 000 001",
            "customer_notes_count": 5,  # 2 this conv + 3 other convs
        },
        "notes": [
            {
                "id": str(uuid4()),
                "content": "Nota de esta conversación",
                "author_user_id": str(uuid4()),
                "author_name": "Operadora",
                "created_at": "2026-01-02T10:00:00+00:00",
                "updated_at": "2026-01-02T10:00:00+00:00",
            },
            {
                "id": str(uuid4()),
                "content": "Segunda nota de esta conversación",
                "author_user_id": str(uuid4()),
                "author_name": "Operadora",
                "created_at": "2026-01-01T10:00:00+00:00",
                "updated_at": "2026-01-01T10:00:00+00:00",
            },
        ],
        "active_escalation": None,
    }

    with patch(
        "api.services.conversation_inbox_service.build_sidebar",
        AsyncMock(return_value=sidebar_data),
    ):
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get(f"/api/admin/conversations/{conv_id}/sidebar")

    assert resp.status_code == 200
    data = resp.json()
    assert data["customer"]["customer_notes_count"] == 5
    assert len(data["notes"]) == 2
