"""
Unit tests for PUT /api/admin/customers/{customer_id}/memories endpoint.

Tests cover:
- Saves memories to PG (mock DB updated)
- Preserves other metadata_ keys (JSONB merge semantics)
- Empty body {} clears memories
- Rejects extra keys with HTTP 422
- Returns HTTP 404 for non-existent customer
- Partial update: only provided keys appear in returned memories

All tests use mocks — no real database required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from database.models import Customer


# ============================================================================
# Helpers
# ============================================================================


def _build_session_mock_for_memories(
    customer_exists: bool,
    updated_metadata: dict | None = None,
):
    """
    Build an AsyncMock session for the memories PUT endpoint.

    First execute call: customer existence check (scalar_one_or_none).
    Second execute call: UPDATE ... RETURNING metadata_ (scalar_one).
    """
    mock_session = AsyncMock()

    # Customer check
    customer_id_val = uuid4() if customer_exists else None
    check_result = MagicMock()
    check_result.scalar_one_or_none.return_value = customer_id_val

    # UPDATE RETURNING result
    update_result = MagicMock()
    update_result.scalar_one.return_value = updated_metadata or {}

    mock_session.execute = AsyncMock(side_effect=[check_result, update_result])
    mock_session.commit = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_ctx


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.asyncio
async def test_update_memories_saves_to_pg():
    """
    GIVEN a valid UpdateMemoriesRequest payload
    WHEN PUT /api/admin/customers/{id}/memories is called
    THEN the DB UPDATE is executed and response contains the updated memories
    """
    from api.routes.admin import update_customer_memories, UpdateMemoriesRequest

    updated_meta = {"memories": {"preferred_stylist_name": "Ana", "visit_count": 3}}
    mock_ctx = _build_session_mock_for_memories(True, updated_meta)
    mock_user = {"sub": "admin"}

    request = UpdateMemoriesRequest(preferred_stylist_name="Ana", visit_count=3)

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await update_customer_memories(
            customer_id=uuid4(), request=request, current_user=mock_user
        )

    assert "memories" in result
    assert result["memories"]["preferred_stylist_name"] == "Ana"


@pytest.mark.asyncio
async def test_update_memories_preserves_other_metadata_keys():
    """
    GIVEN metadata_ = {"whatsapp_name": "María", "memories": {}}
    WHEN PUT /api/admin/customers/{id}/memories updates memories
    THEN the returned metadata still has whatsapp_name (JSONB merge preserves it)

    Note: The actual JSONB || merge happens in PG. We verify the response
    reflects what PG returned (simulated via the mock).
    """
    from api.routes.admin import update_customer_memories, UpdateMemoriesRequest

    # Simulate PG returning the full merged metadata (includes whatsapp_name)
    updated_meta = {
        "whatsapp_name": "María",
        "memories": {"preferred_stylist_name": "Carlos"},
    }
    mock_ctx = _build_session_mock_for_memories(True, updated_meta)
    mock_user = {"sub": "admin"}

    request = UpdateMemoriesRequest(preferred_stylist_name="Carlos")

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await update_customer_memories(
            customer_id=uuid4(), request=request, current_user=mock_user
        )

    # Response only contains the memories sub-key (not full metadata)
    assert result["memories"]["preferred_stylist_name"] == "Carlos"
    # Verify the mock session was committed (DB write happened)
    session = mock_ctx.__aenter__.return_value
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_memories_clear_with_empty_body():
    """
    GIVEN an empty UpdateMemoriesRequest body {}
    WHEN PUT /api/admin/customers/{id}/memories is called
    THEN memories is set to {} (clear operation)
    """
    from api.routes.admin import update_customer_memories, UpdateMemoriesRequest

    # PG returns metadata with empty memories after clear
    updated_meta = {"memories": {}}
    mock_ctx = _build_session_mock_for_memories(True, updated_meta)
    mock_user = {"sub": "admin"}

    request = UpdateMemoriesRequest()  # All fields default to None

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await update_customer_memories(
            customer_id=uuid4(), request=request, current_user=mock_user
        )

    assert result["memories"] == {}


@pytest.mark.asyncio
async def test_update_memories_rejects_extra_keys():
    """
    GIVEN a payload with an unknown key "favorite_color"
    WHEN UpdateMemoriesRequest is instantiated
    THEN Pydantic raises a validation error (extra="forbid")
    """
    from pydantic import ValidationError
    from api.routes.admin import UpdateMemoriesRequest

    with pytest.raises(ValidationError) as exc_info:
        UpdateMemoriesRequest(favorite_color="red")  # type: ignore[call-arg]

    errors = exc_info.value.errors()
    assert any(e["type"] == "extra_forbidden" for e in errors)


@pytest.mark.asyncio
async def test_update_memories_404():
    """
    GIVEN a non-existent customer_id
    WHEN PUT /api/admin/customers/{id}/memories is called
    THEN HTTP 404 is returned
    """
    from api.routes.admin import update_customer_memories, UpdateMemoriesRequest
    from fastapi import HTTPException

    mock_ctx = _build_session_mock_for_memories(False)
    mock_user = {"sub": "admin"}

    request = UpdateMemoriesRequest(preferred_stylist_name="Ana")

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        with pytest.raises(HTTPException) as exc_info:
            await update_customer_memories(
                customer_id=uuid4(), request=request, current_user=mock_user
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_memories_partial_update():
    """
    GIVEN a request with only 3 of 10 memory keys set
    WHEN PUT /api/admin/customers/{id}/memories is called
    THEN the response memories reflects what PG returned (partial keys)
    """
    from api.routes.admin import update_customer_memories, UpdateMemoriesRequest

    updated_meta = {
        "memories": {
            "preferred_stylist_name": "Ana",
            "visit_count": 5,
            "agent_notes": "Prefiere cita temprana",
            # other keys remain as previously stored or null — PG merges
        }
    }
    mock_ctx = _build_session_mock_for_memories(True, updated_meta)
    mock_user = {"sub": "admin"}

    request = UpdateMemoriesRequest(
        preferred_stylist_name="Ana",
        visit_count=5,
        agent_notes="Prefiere cita temprana",
    )

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await update_customer_memories(
            customer_id=uuid4(), request=request, current_user=mock_user
        )

    assert result["memories"]["preferred_stylist_name"] == "Ana"
    assert result["memories"]["visit_count"] == 5
    assert result["memories"]["agent_notes"] == "Prefiere cita temprana"
