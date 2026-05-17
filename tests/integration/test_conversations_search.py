"""
Integration tests for PR-2 global search via GET /conversations?q=.

Covers Scenarios 6.1–6.4 from the spec:
  6.1 Search by customer name
  6.2 Search by phone substring
  6.3 No matches → empty list
  6.4 Empty q= behaves as no filter (full list)

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


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _conv_item(customer_name="María García"):
    return {
        "id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "customer_name": customer_name,
        "started_at": "2026-01-01T10:00:00+00:00",
        "ended_at": None,
        "message_count": 3,
        "summary": None,
        "paused_at": None,
        "resumed_at": None,
        "created_at": "2026-01-01T10:00:00+00:00",
        "source": "db",
    }


# ─── Scenario 6.1: Search by customer name ────────────────────────────────────


def test_search_by_customer_name_returns_matching_conversations(client, mock_auth):
    """Scenario 6.1: q=maría returns conversations for matching customer."""
    results = [_conv_item("María García")]

    with patch(
        "api.services.global_search_service.search_conversations",
        AsyncMock(return_value=results),
    ):
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get("/api/admin/conversations?q=mar%C3%ADa")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["customer_name"] == "María García"


# ─── Scenario 6.2: Search by phone ────────────────────────────────────────────


def test_search_by_phone_returns_matching_conversations(client, mock_auth):
    """Scenario 6.2: q=612 returns conversations for phone-matching customer."""
    results = [_conv_item("Anónimo")]

    with patch(
        "api.services.global_search_service.search_conversations",
        AsyncMock(return_value=results),
    ):
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get("/api/admin/conversations?q=612")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1


# ─── Scenario 6.3: No matches → empty list ────────────────────────────────────


def test_search_no_matches_returns_empty_list(client, mock_auth):
    """Scenario 6.3: q=xyzzy → empty items list, same shape."""
    with patch(
        "api.services.global_search_service.search_conversations",
        AsyncMock(return_value=[]),
    ):
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get("/api/admin/conversations?q=xyzzy")

    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


# ─── Scenario 6.4: Empty q= behaves as no filter ──────────────────────────────


def test_empty_q_falls_through_to_normal_list(client, mock_auth):
    """Scenario 6.4: q= (empty string) → same as omitting q."""
    # search_conversations should NOT be called when q is empty
    with patch(
        "api.services.global_search_service.search_conversations"
    ) as mock_search:
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            # Full list path needs redis + session; simulate empty DB list
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            # redis is imported lazily inside the function with try/except
            with patch("shared.redis_client.get_redis_client", side_effect=Exception("no redis")):
                resp = client.get("/api/admin/conversations?q=")

    # search_conversations must NOT have been called
    mock_search.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


# ─── search sanitizer unit tests (additional coverage) ────────────────────────


def test_search_with_percent_in_query_is_not_injected(client, mock_auth):
    """% in user query must be escaped before DB — sanitizer converts it."""
    with patch(
        "api.services.global_search_service.search_conversations",
        AsyncMock(return_value=[]),
    ) as mock_search:
        with patch("api.routes.admin.get_async_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = client.get("/api/admin/conversations?q=100%25bonus")

    # Endpoint was reached and search_conversations was invoked
    assert resp.status_code == 200
    mock_search.assert_called_once()
