"""
Tests for agent/services/salon_info_service.py — TDD RED phase (T1.1).

These tests cover the 3 read methods of SalonInfoService:
  - get_services() → list[dict]
  - get_hours() → dict
  - get_policies() → dict

DB calls are mocked via patch on `agent.services.salon_info_service.get_async_session`.
No live Postgres required.
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures — fake DB rows
# ---------------------------------------------------------------------------


def make_fake_service(name, audience, category_value, duration, description=None):
    svc = MagicMock()
    svc.name = name
    svc.audience = audience
    cat = MagicMock()
    cat.value = category_value
    svc.category = cat
    svc.duration_minutes = duration
    svc.description = description
    return svc


def make_fake_hours_row(day_of_week, is_closed, start_hour=None, start_minute=None, end_hour=None, end_minute=None):
    row = MagicMock()
    row.day_of_week = day_of_week
    row.is_closed = is_closed
    row.start_hour = start_hour
    row.start_minute = start_minute
    row.end_hour = end_hour
    row.end_minute = end_minute
    return row


def make_fake_policy(key, value):
    row = MagicMock()
    row.key = key
    row.value = value
    return row


FAKE_SERVICE_ROWS = [
    make_fake_service("Corte Dama", "adult_female", "HAIRDRESSING", 40),
    make_fake_service("Manicura", None, "AESTHETICS", 30),
]

FAKE_HOURS_ROWS = [
    make_fake_hours_row(0, True),
    make_fake_hours_row(1, False, 10, 0, 20, 0),
    make_fake_hours_row(2, False, 10, 0, 20, 0),
    make_fake_hours_row(3, False, 10, 0, 20, 0),
    make_fake_hours_row(4, False, 10, 0, 20, 0),
    make_fake_hours_row(5, False, 9, 0, 14, 0),
    make_fake_hours_row(6, True),
]

FAKE_POLICY_ROWS = [
    make_fake_policy("faq:hours", "Abierto martes a viernes 10-20"),
    make_fake_policy("faq:parking", "Hay parking público cerca"),
]


# ---------------------------------------------------------------------------
# Helper — build a mock async session that returns scalars results
# ---------------------------------------------------------------------------


def make_session_ctx(scalars_result):
    """Return an async context manager mock whose session.execute(...)
    returns scalars().all() = scalars_result."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = scalars_result

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def fake_session_ctx():
        yield mock_session

    return fake_session_ctx


# ---------------------------------------------------------------------------
# T1.1 — test_get_services_success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_services_success():
    """SalonInfoService.get_services() returns a list of dicts with the expected keys."""
    from agent.services.salon_info_service import SalonInfoService

    ctx = make_session_ctx(FAKE_SERVICE_ROWS)
    with patch("agent.services.salon_info_service.get_async_session", ctx):
        result = await SalonInfoService.get_services()

    assert isinstance(result, list)
    assert len(result) == 2
    first = result[0]
    assert first["name"] == "Corte Dama"
    assert first["audience"] == "adult_female"
    assert first["category"] == "HAIRDRESSING"
    assert first["duration_minutes"] == 40


@pytest.mark.asyncio
async def test_get_services_returns_description_field():
    """Each service dict includes description (may be None)."""
    from agent.services.salon_info_service import SalonInfoService

    ctx = make_session_ctx(FAKE_SERVICE_ROWS)
    with patch("agent.services.salon_info_service.get_async_session", ctx):
        result = await SalonInfoService.get_services()

    for item in result:
        assert "description" in item


# ---------------------------------------------------------------------------
# T1.1 — test_get_hours_success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_hours_success():
    """SalonInfoService.get_hours() returns a dict keyed by day-of-week string."""
    from agent.services.salon_info_service import SalonInfoService

    ctx = make_session_ctx(FAKE_HOURS_ROWS)
    with patch("agent.services.salon_info_service.get_async_session", ctx):
        result = await SalonInfoService.get_hours()

    assert isinstance(result, dict)
    assert len(result) == 7


@pytest.mark.asyncio
async def test_get_hours_closed_days():
    """Closed days return {'is_closed': True}."""
    from agent.services.salon_info_service import SalonInfoService

    ctx = make_session_ctx(FAKE_HOURS_ROWS)
    with patch("agent.services.salon_info_service.get_async_session", ctx):
        result = await SalonInfoService.get_hours()

    assert result["0"]["is_closed"] is True
    assert result["6"]["is_closed"] is True


@pytest.mark.asyncio
async def test_get_hours_open_days_have_time_strings():
    """Open days include 'open' and 'close' formatted as 'HH:MM'."""
    from agent.services.salon_info_service import SalonInfoService

    ctx = make_session_ctx(FAKE_HOURS_ROWS)
    with patch("agent.services.salon_info_service.get_async_session", ctx):
        result = await SalonInfoService.get_hours()

    tuesday = result["1"]
    assert tuesday["is_closed"] is False
    assert tuesday["open"] == "10:00"
    assert tuesday["close"] == "20:00"


# ---------------------------------------------------------------------------
# T1.1 — test_get_policies_success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_policies_success():
    """SalonInfoService.get_policies() returns a dict keyed by policy key."""
    from agent.services.salon_info_service import SalonInfoService

    ctx = make_session_ctx(FAKE_POLICY_ROWS)
    with patch("agent.services.salon_info_service.get_async_session", ctx):
        result = await SalonInfoService.get_policies()

    assert isinstance(result, dict)
    assert "faq:hours" in result
    assert result["faq:hours"] == "Abierto martes a viernes 10-20"


@pytest.mark.asyncio
async def test_get_policies_empty_db():
    """get_policies() returns empty dict when no faq: policies exist."""
    from agent.services.salon_info_service import SalonInfoService

    ctx = make_session_ctx([])
    with patch("agent.services.salon_info_service.get_async_session", ctx):
        result = await SalonInfoService.get_policies()

    assert result == {}
