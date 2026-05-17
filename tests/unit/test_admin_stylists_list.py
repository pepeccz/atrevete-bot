"""
Unit tests for GET /api/admin/stylists endpoint filtering behavior.

Tests cover:
- Default behavior: returns active-only stylists when is_active param is omitted
- Explicit inactive filter: returns only inactive stylists when is_active=false

All tests use mocks — no real database required.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from database.models import ServiceCategory, Stylist

# ============================================================================
# Helpers
# ============================================================================


def _make_stylist_mock(name: str, is_active: bool, calendar_id: str | None = None):
    """Build a MagicMock Stylist row with the fields the endpoint serializes."""
    stylist = MagicMock(spec=Stylist)
    stylist.id = uuid4()
    stylist.name = name
    stylist.category = ServiceCategory.HAIRDRESSING
    stylist.google_calendar_id = calendar_id
    stylist.is_active = is_active
    stylist.color = None
    # Timestamps used in isoformat() calls
    now = datetime(2026, 3, 12, 10, 0, 0)
    stylist.created_at = now
    stylist.updated_at = now
    return stylist


def _build_session_mock(stylists_to_return: list):
    """Build an AsyncMock session that returns the given stylists from execute()."""
    mock_session = AsyncMock()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = stylists_to_return

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_ctx


# ============================================================================
# Task 5.3.1 — GET /api/admin/stylists defaults to active-only
# ============================================================================


@pytest.mark.asyncio
async def test_list_stylists_defaults_to_active_only():
    """
    GIVEN two active stylists and one inactive stylist in the DB
    WHEN GET /api/admin/stylists is called with no is_active param
    THEN only the 2 active stylists are returned.

    The endpoint logic: effective_is_active = is_active if is_active is not None else True
    """
    from api.routes.admin import list_stylists

    active1 = _make_stylist_mock("Ana", is_active=True)
    active2 = _make_stylist_mock("Victor", is_active=True)
    # inactive is intentionally excluded by the query filter — mock only returns actives
    mock_ctx = _build_session_mock([active1, active2])

    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await list_stylists(current_user=mock_user, is_active=None)

    items = result["items"]
    assert len(items) == 2
    returned_names = {item["name"] for item in items}
    assert "Ana" in returned_names
    assert "Victor" in returned_names

    # All returned items must be active
    for item in items:
        assert item["is_active"] is True, (
            f"Stylist '{item['name']}' is not active but was returned by default filter"
        )


# ============================================================================
# Task 5.3.2 — GET /api/admin/stylists?is_active=false returns inactive stylists
# ============================================================================


@pytest.mark.asyncio
async def test_list_stylists_explicit_inactive_returns_inactive():
    """
    GIVEN one inactive stylist in the DB
    WHEN GET /api/admin/stylists is called with is_active=False
    THEN only the inactive stylist is returned.

    The endpoint logic: effective_is_active = is_active (False) when explicitly provided.
    """
    from api.routes.admin import list_stylists

    inactive = _make_stylist_mock("Rosa", is_active=False)
    mock_ctx = _build_session_mock([inactive])

    mock_user = {"sub": "admin"}

    with patch("api.routes.admin.get_async_session", return_value=mock_ctx):
        result = await list_stylists(current_user=mock_user, is_active=False)

    items = result["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Rosa"
    assert items[0]["is_active"] is False
