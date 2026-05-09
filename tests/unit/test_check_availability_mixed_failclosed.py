"""T-7 — RED tests for check_availability fail-closed mixed-service defense.

Tests that _get_active_stylists_for_services returns [] when services span
HAIRDRESSING + AESTHETICS (no BOTH) — was incorrectly returning all active stylists.

All tests use mocks — no DB required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_session_ctx():
    session_mock = AsyncMock()
    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=session_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)
    return ctx_mock, session_mock


@pytest.mark.asyncio
async def test_get_active_stylists_for_services_mixed_returns_empty():
    """Mixed HAIRDRESSING + AESTHETICS services → [] (fail-closed, was: all active)."""
    from uuid import uuid4
    from database.models import ServiceCategory

    hair_id = uuid4()
    aesth_id = uuid4()

    # Mock the DB to return one HAIRDRESSING and one AESTHETICS category
    session_mock = AsyncMock()
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [
        (ServiceCategory.HAIRDRESSING,),
        (ServiceCategory.AESTHETICS,),
    ]
    session_mock.execute = AsyncMock(return_value=result_mock)

    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=session_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.services.availability_service.get_async_session", return_value=ctx_mock):
        from agent.services.availability_service import get_active_stylists_for_services

        result = await get_active_stylists_for_services(
            service_ids=[hair_id, aesth_id],
            audience=None,
        )

    assert result == [], f"Expected empty list for mixed services, got: {result}"


@pytest.mark.asyncio
async def test_get_active_stylists_for_services_hairdressing_only_returns_hair_stylists():
    """HAIRDRESSING-only services → returns HAIRDRESSING stylist IDs (existing behavior preserved)."""
    from uuid import uuid4
    from database.models import ServiceCategory

    hair_svc_id = uuid4()
    hair_stylist_id = uuid4()
    both_stylist_id = uuid4()

    execute_count = 0

    async def _fake_execute(stmt):
        nonlocal execute_count
        execute_count += 1
        mock_result = MagicMock()
        if execute_count == 1:
            # First call: service category query
            mock_result.fetchall.return_value = [(ServiceCategory.HAIRDRESSING,)]
        else:
            # Second call: stylist query
            mock_result.fetchall.return_value = [(hair_stylist_id,), (both_stylist_id,)]
        return mock_result

    session_mock = AsyncMock()
    session_mock.execute = _fake_execute

    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=session_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.services.availability_service.get_async_session", return_value=ctx_mock):
        from agent.services.availability_service import get_active_stylists_for_services

        result = await get_active_stylists_for_services(
            service_ids=[hair_svc_id],
            audience=None,
        )

    assert len(result) == 2
    assert hair_stylist_id in result
    assert both_stylist_id in result
