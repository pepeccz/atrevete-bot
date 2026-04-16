"""
Tests for availability_tools module — verifies simplified v5.0 schema.

Checks:
- CheckAvailabilitySchema has the new fields (service_name, date, stylist_name, time_range)
- find_next_available was removed (merged into check_availability AUTO-SEARCH logic)
- Old schema fields (service_category, service_duration_minutes) are gone
- date_is_closed is included in base_response and set correctly for holidays/closed days
"""

import inspect
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from agent.tools.availability_tools import CheckAvailabilitySchema, check_availability


def test_schema_has_service_names():
    """CheckAvailabilitySchema has service_names field (list[str])."""
    fields = CheckAvailabilitySchema.model_fields
    assert "service_names" in fields, "service_names field is missing from CheckAvailabilitySchema"


def test_schema_service_names_is_list():
    """service_names field accepts a list of strings."""
    schema = CheckAvailabilitySchema(service_names=["Cortar", "Cultura de Color"], date="2026-04-10")
    assert schema.service_names == ["Cortar", "Cultura de Color"]


def test_schema_service_names_single():
    """service_names field works with a single service (list of 1)."""
    schema = CheckAvailabilitySchema(service_names=["Cortar"], date="2026-04-10")
    assert schema.service_names == ["Cortar"]


def test_schema_has_date():
    """CheckAvailabilitySchema has date field."""
    fields = CheckAvailabilitySchema.model_fields
    assert "date" in fields, "date field is missing from CheckAvailabilitySchema"


def test_schema_has_stylist_name():
    """CheckAvailabilitySchema has stylist_name field (replaces stylist_id)."""
    fields = CheckAvailabilitySchema.model_fields
    assert "stylist_name" in fields, "stylist_name field is missing from CheckAvailabilitySchema"


def test_schema_has_time_range():
    """CheckAvailabilitySchema has time_range field."""
    fields = CheckAvailabilitySchema.model_fields
    assert "time_range" in fields, "time_range field is missing from CheckAvailabilitySchema"


def test_no_find_next_available():
    """find_next_available was removed — merged into check_availability AUTO-SEARCH."""
    import agent.tools.availability_tools as module

    assert not hasattr(module, "find_next_available"), (
        "find_next_available should not exist — it was merged into check_availability AUTO-SEARCH"
    )


def test_no_old_schema_fields():
    """Old fields service_category and service_duration_minutes are gone from schema."""
    import agent.tools.availability_tools as module

    source = inspect.getsource(module)
    assert "service_category" not in CheckAvailabilitySchema.model_fields, (
        "service_category should not be a schema field in the simplified architecture"
    )
    assert "service_duration_minutes" not in CheckAvailabilitySchema.model_fields, (
        "service_duration_minutes should not be a schema field — duration is resolved internally"
    )


# ── date_is_closed tests ───────────────────────────────────────────────────────


def _make_mock_service(name="Cortar", duration=30, category_value="peluqueria"):
    """Build a minimal mock Service object."""
    from unittest.mock import MagicMock
    from database.models import ServiceCategory

    svc = MagicMock()
    svc.name = name
    svc.duration_minutes = duration
    svc.category = ServiceCategory.HAIRDRESSING
    svc.is_active = True
    return svc


def _make_mock_stylist(name="Laura"):
    """Build a minimal mock Stylist object."""
    from unittest.mock import MagicMock
    from database.models import ServiceCategory

    stylist = MagicMock()
    stylist.name = name
    stylist.id = "00000000-0000-0000-0000-000000000001"
    stylist.category = ServiceCategory.HAIRDRESSING
    stylist.is_active = True
    return stylist


def _make_booking_config():
    """Build a minimal mock booking config."""
    from unittest.mock import MagicMock

    cfg = MagicMock()
    cfg.auto_search_extra_days = 3
    cfg.max_slots_to_present = 5
    cfg.max_slots_per_day = 2
    cfg.slot_diversification_strategy = MagicMock(value="none")
    return cfg


@pytest.mark.asyncio
async def test_date_is_closed_false_on_open_day():
    """Open day with available slots returns date_is_closed=False."""
    mock_service = _make_mock_service()
    mock_stylist = _make_mock_stylist()
    mock_slot = {
        "time": "10:00",
        "end_time": "10:30",
        "date": "2026-04-17",
        "full_datetime": "2026-04-17T10:00:00",
    }

    with (
        patch(
            "agent.tools.availability_tools._resolve_service_by_name",
            new=AsyncMock(return_value=mock_service),
        ),
        patch(
            "agent.tools.availability_tools._get_active_stylists_for_category",
            new=AsyncMock(return_value=[mock_stylist]),
        ),
        patch(
            "agent.tools.availability_tools.validate_3_day_rule",
            new=AsyncMock(return_value={"valid": True}),
        ),
        patch(
            "agent.tools.availability_tools.is_holiday",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent.tools.availability_tools.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "agent.tools.availability_tools._collect_slots_for_date",
            new=AsyncMock(return_value=[mock_slot]),
        ),
        patch(
            "agent.tools.availability_tools.get_booking_config",
            new=AsyncMock(return_value=_make_booking_config()),
        ),
    ):
        result = await check_availability.ainvoke(
            {"service_names": ["Cortar"], "date": "2026-04-17"}
        )

    assert result["success"] is True
    assert result["date_is_closed"] is False


@pytest.mark.asyncio
async def test_date_is_closed_true_on_closed_day():
    """Closed business day returns date_is_closed=True and alternative_dates=True."""
    mock_service = _make_mock_service()
    mock_stylist = _make_mock_stylist()
    mock_slot = {
        "time": "10:00",
        "end_time": "10:30",
        "date": "2026-04-21",
        "full_datetime": "2026-04-21T10:00:00",
    }

    with (
        patch(
            "agent.tools.availability_tools._resolve_service_by_name",
            new=AsyncMock(return_value=mock_service),
        ),
        patch(
            "agent.tools.availability_tools._get_active_stylists_for_category",
            new=AsyncMock(return_value=[mock_stylist]),
        ),
        patch(
            "agent.tools.availability_tools.validate_3_day_rule",
            new=AsyncMock(return_value={"valid": True}),
        ),
        patch(
            "agent.tools.availability_tools.is_holiday",
            new=AsyncMock(return_value=None),  # Not a holiday
        ),
        patch(
            "agent.tools.availability_tools.is_date_closed",
            # First call (requested date): closed. Subsequent auto-search calls: open.
            new=AsyncMock(side_effect=[True, False, False, False]),
        ),
        patch(
            "agent.tools.availability_tools._collect_slots_for_date",
            new=AsyncMock(return_value=[mock_slot]),
        ),
        patch(
            "agent.tools.availability_tools.get_booking_config",
            new=AsyncMock(return_value=_make_booking_config()),
        ),
    ):
        result = await check_availability.ainvoke(
            {"service_names": ["Cortar"], "date": "2026-04-19"}  # Sunday
        )

    assert result["date_is_closed"] is True
    assert result["alternative_dates"] is True


@pytest.mark.asyncio
async def test_date_is_closed_true_on_holiday():
    """Holiday returns date_is_closed=True and holiday_detected=True."""
    mock_service = _make_mock_service()
    mock_stylist = _make_mock_stylist()
    mock_slot = {
        "time": "10:00",
        "end_time": "10:30",
        "date": "2026-05-02",
        "full_datetime": "2026-05-02T10:00:00",
    }

    with (
        patch(
            "agent.tools.availability_tools._resolve_service_by_name",
            new=AsyncMock(return_value=mock_service),
        ),
        patch(
            "agent.tools.availability_tools._get_active_stylists_for_category",
            new=AsyncMock(return_value=[mock_stylist]),
        ),
        patch(
            "agent.tools.availability_tools.validate_3_day_rule",
            new=AsyncMock(return_value={"valid": True}),
        ),
        patch(
            "agent.tools.availability_tools.is_holiday",
            # First call: holiday on requested date; subsequent: not holiday
            new=AsyncMock(side_effect=["Día del Trabajo", None, None, None]),
        ),
        patch(
            "agent.tools.availability_tools.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "agent.tools.availability_tools._collect_slots_for_date",
            new=AsyncMock(return_value=[mock_slot]),
        ),
        patch(
            "agent.tools.availability_tools.get_booking_config",
            new=AsyncMock(return_value=_make_booking_config()),
        ),
    ):
        result = await check_availability.ainvoke(
            {"service_names": ["Cortar"], "date": "2026-05-01"}
        )

    assert result["date_is_closed"] is True
    assert result["holiday_detected"] is True
    assert result["alternative_dates"] is True
