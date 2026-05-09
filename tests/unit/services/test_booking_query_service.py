"""
Tests for agent/services/booking_query_service.py — TDD RED phase (T2.1).

Covers:
  - resolve_stylist(name) → UUID | None
  - resolve_service_ids(names) → (resolved_ids, unknown_names)
  - resolve_audience_variants(service_name) → (kind, family, candidates)
  - resolve_service_categories(service_ids) → set
  - resolve_service_id_to_category_map(service_ids) → dict
  - resolve_active_stylists(service_ids) → list[str]
  - resolve_all(...) facade — single session, returns ResolveAllResult

DB calls are mocked via patch on
`agent.services.booking_query_service.get_async_session`.
No live Postgres required.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers — fake async session factory
# ---------------------------------------------------------------------------


def make_fake_session(rows=None):
    """Return a fake AsyncSession that returns *rows* from execute()."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows or []
    result_mock.first.return_value = rows[0] if rows else None
    session.execute = AsyncMock(return_value=result_mock)
    return session


@asynccontextmanager
async def fake_session_ctx(session):
    yield session


# ---------------------------------------------------------------------------
# T2.1 a — resolve_stylist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_stylist_found():
    """resolve_stylist returns UUID when name matches (normalized)."""
    from agent.services.booking_query_service import BookingQueryService

    stylist_id = uuid4()
    fake_session = make_fake_session(rows=[(stylist_id, "Marta García")])

    with patch(
        "agent.services.booking_query_service.get_async_session",
        return_value=fake_session_ctx(fake_session),
    ):
        result = await BookingQueryService.resolve_stylist("marta garcia")

    assert result == stylist_id


@pytest.mark.asyncio
async def test_resolve_stylist_not_found():
    """resolve_stylist returns None when no active stylist matches."""
    from agent.services.booking_query_service import BookingQueryService

    fake_session = make_fake_session(rows=[])

    with patch(
        "agent.services.booking_query_service.get_async_session",
        return_value=fake_session_ctx(fake_session),
    ):
        result = await BookingQueryService.resolve_stylist("fantasma xyz")

    assert result is None


# ---------------------------------------------------------------------------
# T2.1 b — resolve_service_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_service_ids_known_service():
    """resolve_service_ids returns (resolved_ids, []) for a recognized service name."""
    from agent.services.booking_query_service import BookingQueryService

    service_id = uuid4()
    # DB returns (id, name) rows
    fake_session = make_fake_session(rows=[(service_id, "Corte Dama")])

    with patch(
        "agent.services.booking_query_service.get_async_session",
        return_value=fake_session_ctx(fake_session),
    ):
        resolved, unknown = await BookingQueryService.resolve_service_ids(["corte dama"])

    assert str(service_id) in resolved
    assert unknown == []


@pytest.mark.asyncio
async def test_resolve_service_ids_unknown_service():
    """resolve_service_ids returns ([], [name]) for an unrecognized service."""
    from agent.services.booking_query_service import BookingQueryService

    fake_session = make_fake_session(rows=[])

    with patch(
        "agent.services.booking_query_service.get_async_session",
        return_value=fake_session_ctx(fake_session),
    ):
        resolved, unknown = await BookingQueryService.resolve_service_ids(["servicio_xyz"])

    assert resolved == []
    assert "servicio_xyz" in unknown


# ---------------------------------------------------------------------------
# T2.1 c — resolve_audience_variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_audience_variants_none_when_no_row():
    """resolve_audience_variants returns ('none', '', []) when service not found."""
    from agent.services.booking_query_service import BookingQueryService

    fake_session = make_fake_session(rows=[])

    with patch(
        "agent.services.booking_query_service.get_async_session",
        return_value=fake_session_ctx(fake_session),
    ):
        kind, family, candidates = await BookingQueryService.resolve_audience_variants("servicio_xyz")

    assert kind == "none"
    assert family == ""
    assert candidates == []


# ---------------------------------------------------------------------------
# T2.1 d — resolve_active_stylists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_active_stylists_returns_first_names():
    """resolve_active_stylists returns list of first names (before first space)."""
    from agent.services.booking_query_service import BookingQueryService

    fake_session = make_fake_session(rows=[("Marta García",), ("Pilar López",)])

    with patch(
        "agent.services.booking_query_service.get_async_session",
        return_value=fake_session_ctx(fake_session),
    ):
        result = await BookingQueryService.resolve_active_stylists()

    assert "Marta" in result
    assert "Pilar" in result


# ---------------------------------------------------------------------------
# T2.1 e — resolve_all facade (single session behavior)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_all_uses_single_session():
    """resolve_all opens exactly ONE session for the entire resolution chain."""
    from agent.services.booking_query_service import BookingQueryService

    session_enter_count = 0

    @asynccontextmanager
    async def counting_session_ctx():
        nonlocal session_enter_count
        session_enter_count += 1
        fake_session = make_fake_session(rows=[])
        yield fake_session

    with patch(
        "agent.services.booking_query_service.get_async_session",
        side_effect=counting_session_ctx,
    ):
        result = await BookingQueryService.resolve_all(
            services=["corte dama"],
            stylist_name=None,
            audience=None,
        )

    # Only ONE session context should have been entered
    assert session_enter_count == 1, (
        f"Expected exactly 1 session open, got {session_enter_count}"
    )


@pytest.mark.asyncio
async def test_resolve_all_returns_result_dataclass():
    """resolve_all returns a ResolveAllResult dataclass with expected fields."""
    from agent.services.booking_query_service import BookingQueryService, ResolveAllResult

    fake_session = make_fake_session(rows=[])

    with patch(
        "agent.services.booking_query_service.get_async_session",
        return_value=fake_session_ctx(fake_session),
    ):
        result = await BookingQueryService.resolve_all(
            services=["corte dama"],
            stylist_name=None,
            audience=None,
        )

    assert isinstance(result, ResolveAllResult)
    assert hasattr(result, "success")
    assert hasattr(result, "stylist_id")
    assert hasattr(result, "service_ids")
    assert hasattr(result, "audience_variants")
    assert hasattr(result, "categories")
    assert hasattr(result, "id_to_category")
    assert hasattr(result, "active_stylists")
    assert hasattr(result, "error_message")


@pytest.mark.asyncio
async def test_resolve_all_success_with_known_service():
    """resolve_all returns success=True and populated service_ids for a known service."""
    from agent.services.booking_query_service import BookingQueryService

    service_id = uuid4()

    # We need to mock multiple DB queries inside ONE session
    # The session will be called multiple times for different queries
    session = AsyncMock()

    service_result = MagicMock()
    service_result.fetchall.return_value = [(service_id, "Corte Dama")]

    empty_result = MagicMock()
    empty_result.fetchall.return_value = []
    empty_result.first.return_value = None

    # First call: resolve_service_ids query
    # Subsequent calls: audience variants, categories, etc.
    session.execute = AsyncMock(side_effect=[
        service_result,  # resolve_service_ids
        empty_result,    # resolve_audience_variants — first() call
        empty_result,    # resolve_service_categories
        empty_result,    # resolve_service_id_to_category_map
        empty_result,    # resolve_active_stylists (legacy path)
    ])

    with patch(
        "agent.services.booking_query_service.get_async_session",
        return_value=fake_session_ctx(session),
    ):
        result = await BookingQueryService.resolve_all(
            services=["corte dama"],
            stylist_name=None,
            audience=None,
        )

    assert result.success is True
    assert str(service_id) in result.service_ids
