"""
Tests for the 4 DB-helper methods added to AvailabilityService — T3.1 (RED).

Covers:
  - get_service_durations(service_ids) → dict[UUID, int]
  - get_active_stylists_for_services(service_ids, audience) → list[UUID]
  - get_stylist_name(stylist_id) → str
  - get_stylist_names_map(stylist_ids) → dict[UUID, str]

DB calls are mocked via patch on `agent.services.availability_service.get_async_session`.
No live Postgres required.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Shared UUIDs
# ---------------------------------------------------------------------------

FAKE_SERVICE_A = uuid4()
FAKE_SERVICE_B = uuid4()
FAKE_STYLIST_A = uuid4()
FAKE_STYLIST_B = uuid4()


# ---------------------------------------------------------------------------
# Helpers — mock session factory
# ---------------------------------------------------------------------------


def make_mock_session(fetchall_rows=None, first_row=None):
    """Return a context-manager mock whose session.execute returns configured rows."""
    mock_result = MagicMock()
    if fetchall_rows is not None:
        mock_result.fetchall.return_value = fetchall_rows
    if first_row is not None:
        mock_result.first.return_value = first_row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _cm():
        yield mock_session

    return _cm


# ---------------------------------------------------------------------------
# T3.1.A — get_service_durations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_service_durations_returns_uuid_to_minutes_map():
    """get_service_durations returns {uuid: duration_minutes} for each service id."""
    from agent.services.availability_service import get_service_durations

    rows = [(FAKE_SERVICE_A, 45), (FAKE_SERVICE_B, 30)]
    mock_session = make_mock_session(fetchall_rows=rows)

    with patch("agent.services.availability_service.get_async_session", mock_session):
        result = await get_service_durations([FAKE_SERVICE_A, FAKE_SERVICE_B])

    assert result == {FAKE_SERVICE_A: 45, FAKE_SERVICE_B: 30}


@pytest.mark.asyncio
async def test_get_service_durations_empty_list_returns_empty_dict():
    """get_service_durations with empty list returns empty dict without hitting DB."""
    from agent.services.availability_service import get_service_durations

    mock_session = make_mock_session(fetchall_rows=[])

    with patch("agent.services.availability_service.get_async_session", mock_session):
        result = await get_service_durations([])

    assert result == {}


# ---------------------------------------------------------------------------
# T3.1.B — get_active_stylists_for_services
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_stylists_for_services_returns_list_of_uuids():
    """get_active_stylists_for_services returns list of active stylist UUIDs."""
    from agent.services.availability_service import get_active_stylists_for_services

    # Two separate execute calls: one for categories, one for stylist ids
    cat_mock = MagicMock()
    # Simulate HAIRDRESSING-only category
    from database.models import ServiceCategory

    cat_mock.fetchall.return_value = [(ServiceCategory.HAIRDRESSING,)]

    stylist_mock = MagicMock()
    stylist_mock.fetchall.return_value = [(FAKE_STYLIST_A,), (FAKE_STYLIST_B,)]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[cat_mock, stylist_mock])

    @asynccontextmanager
    async def _cm():
        yield mock_session

    with patch("agent.services.availability_service.get_async_session", _cm):
        result = await get_active_stylists_for_services(
            [FAKE_SERVICE_A], audience="adult_female"
        )

    assert FAKE_STYLIST_A in result
    assert FAKE_STYLIST_B in result


@pytest.mark.asyncio
async def test_get_active_stylists_for_services_mixed_returns_empty():
    """Mixed HAIR+AESTHETICS without BOTH category returns empty list (fail-closed)."""
    from agent.services.availability_service import get_active_stylists_for_services
    from database.models import ServiceCategory

    cat_mock = MagicMock()
    cat_mock.fetchall.return_value = [
        (ServiceCategory.HAIRDRESSING,),
        (ServiceCategory.AESTHETICS,),
    ]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=cat_mock)

    @asynccontextmanager
    async def _cm():
        yield mock_session

    with patch("agent.services.availability_service.get_async_session", _cm):
        result = await get_active_stylists_for_services(
            [FAKE_SERVICE_A, FAKE_SERVICE_B], audience=None
        )

    assert result == []


# ---------------------------------------------------------------------------
# T3.1.C — get_stylist_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_stylist_name_returns_name_string():
    """get_stylist_name returns the stylist's name for a known ID."""
    from agent.services.availability_service import get_stylist_name

    mock_result = MagicMock()
    mock_result.first.return_value = ("María",)
    mock_session = make_mock_session()
    mock_session_instance = AsyncMock()
    mock_session_instance.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _cm():
        yield mock_session_instance

    with patch("agent.services.availability_service.get_async_session", _cm):
        result = await get_stylist_name(FAKE_STYLIST_A)

    assert result == "María"


@pytest.mark.asyncio
async def test_get_stylist_name_unknown_id_returns_uuid_string():
    """get_stylist_name returns str(stylist_id) if not found in DB."""
    from agent.services.availability_service import get_stylist_name

    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_session_instance = AsyncMock()
    mock_session_instance.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _cm():
        yield mock_session_instance

    with patch("agent.services.availability_service.get_async_session", _cm):
        result = await get_stylist_name(FAKE_STYLIST_A)

    assert result == str(FAKE_STYLIST_A)


# ---------------------------------------------------------------------------
# T3.1.D — get_stylist_names_map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_stylist_names_map_returns_uuid_to_name_dict():
    """get_stylist_names_map returns {uuid: name} for each stylist id."""
    from agent.services.availability_service import get_stylist_names_map

    rows = [(FAKE_STYLIST_A, "Marta"), (FAKE_STYLIST_B, "Laura")]
    mock_session = make_mock_session(fetchall_rows=rows)

    with patch("agent.services.availability_service.get_async_session", mock_session):
        result = await get_stylist_names_map([FAKE_STYLIST_A, FAKE_STYLIST_B])

    assert result == {FAKE_STYLIST_A: "Marta", FAKE_STYLIST_B: "Laura"}


@pytest.mark.asyncio
async def test_get_stylist_names_map_empty_list_returns_empty_without_db_call():
    """get_stylist_names_map with empty list returns {} without hitting DB."""
    from agent.services.availability_service import get_stylist_names_map

    # No mock needed — should short-circuit before DB call
    result = await get_stylist_names_map([])

    assert result == {}
