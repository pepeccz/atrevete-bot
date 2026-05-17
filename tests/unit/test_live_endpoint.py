"""Unit tests for GET /api/admin/conversations/{id}/live endpoint.

Tests follow Strict TDD: written RED first, then made GREEN by implementation.

Covered spec scenarios:
  2.6 - active conversation with checkpoint + summary -> 200, source=redis, non-null summary
  2.7 - checkpoint exists but < 20 messages -> summary=null, source=redis
  2.8 - no checkpoint -> 200, source="null", all other fields null

Authentication: the endpoint uses get_current_user dependency; tests override it.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App fixture with auth override
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """FastAPI test client with admin auth bypassed."""
    from api.main import app
    from api.routes.admin import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": "admin", "role": "admin"}
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers to build mock checkpoint tuples
# ---------------------------------------------------------------------------


def _make_checkpoint_tuple(summary: str | None, message_count: int, ts: str = "2026-04-28T10:00:00Z"):
    """Build a minimal mock object resembling a LangGraph CheckpointTuple."""
    messages = [MagicMock() for _ in range(message_count)]
    tpl = MagicMock()
    tpl.checkpoint = {
        "channel_values": {
            "conversation_summary": summary,
            "messages": messages,
        },
        "ts": ts,
    }
    return tpl


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLiveEndpointWithCheckpoint:
    """Scenarios where a Redis checkpoint exists."""

    def test_live_returns_200_with_redis_source(self, client):
        """Active conversation with summary -> source=redis, non-null summary."""
        conversation_id = str(uuid4())
        checkpoint_tuple = _make_checkpoint_tuple(
            summary="El cliente quiere corte y color.",
            message_count=25,
        )
        mock_saver = AsyncMock()
        mock_saver.aget_tuple = AsyncMock(return_value=checkpoint_tuple)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_saver)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.checkpointer.get_checkpointer", return_value=mock_ctx):
            response = client.get(f"/api/admin/conversations/{conversation_id}/live")

        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "redis"
        assert body["summary"] == "El cliente quiere corte y color."
        assert body["message_count"] == 25

    def test_live_returns_null_summary_when_message_count_lt_20(self, client):
        """Checkpoint with 15 messages -> summary=null, source=redis."""
        conversation_id = str(uuid4())
        checkpoint_tuple = _make_checkpoint_tuple(
            summary="summary that should be hidden",
            message_count=15,
        )
        mock_saver = AsyncMock()
        mock_saver.aget_tuple = AsyncMock(return_value=checkpoint_tuple)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_saver)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.checkpointer.get_checkpointer", return_value=mock_ctx):
            response = client.get(f"/api/admin/conversations/{conversation_id}/live")

        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "redis"
        assert body["summary"] is None
        assert body["message_count"] == 15


class TestLiveEndpointNoCheckpoint:
    """Scenario where no Redis checkpoint exists."""

    def test_live_returns_200_null_body_when_no_checkpoint(self, client):
        """No checkpoint -> 200, source='null', all other fields null."""
        conversation_id = str(uuid4())
        mock_saver = AsyncMock()
        mock_saver.aget_tuple = AsyncMock(return_value=None)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_saver)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.checkpointer.get_checkpointer", return_value=mock_ctx):
            response = client.get(f"/api/admin/conversations/{conversation_id}/live")

        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "null"
        assert body["summary"] is None
        assert body["message_count"] is None
        assert body["last_updated"] is None
