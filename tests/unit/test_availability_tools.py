from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agent.modes.booking_context_v7 import InterpretationReason
from agent.tools import availability_tools as availability_tools_module


def _make_stylist(name: str = "Ana") -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name=name)


@pytest.mark.asyncio
async def test_find_next_available_returns_semantic_fields_when_date_is_substituted():
    preferred_date = datetime.now(availability_tools_module.MADRID_TZ) + timedelta(days=1)
    min_valid_before = (
        datetime.now(availability_tools_module.MADRID_TZ) + timedelta(days=availability_tools_module.MINIMUM_DAYS)
    ).date().isoformat()
    min_valid_after = (
        datetime.now(availability_tools_module.MADRID_TZ) + timedelta(days=availability_tools_module.MINIMUM_DAYS)
    ).date().isoformat()
    stylist = _make_stylist()

    with patch.object(
        availability_tools_module,
        "parse_natural_date",
        return_value=preferred_date,
    ), patch.object(
        availability_tools_module,
        "get_stylists_by_category",
        new=AsyncMock(return_value=[stylist]),
    ), patch.object(
        availability_tools_module,
        "get_next_open_date",
        new=AsyncMock(side_effect=lambda value, max_search_days=14: value),
    ), patch.object(
        availability_tools_module,
        "is_date_closed",
        new=AsyncMock(return_value=False),
    ), patch.object(
        availability_tools_module,
        "is_holiday",
        new=AsyncMock(return_value=None),
    ), patch.object(
        availability_tools_module,
        "get_available_slots",
        new=AsyncMock(
            return_value=[
                {
                    "time": "10:00",
                    "end_time": "11:00",
                    "full_datetime": "2026-03-22T10:00:00+01:00",
                }
            ]
        ),
    ):
        result = await availability_tools_module.find_next_available.ainvoke(
            {
                "service_category": "Peluquería",
                "start_date": "mañana",
                "max_days_to_search": 1,
            }
        )

    assert result["substitution_made"] is True
    assert result["date_requested"] == preferred_date.date().isoformat()
    assert result["date_substituted"] == result["min_valid_date"]
    assert result["substitution_reason"] == InterpretationReason.MINIMUM_DAYS_RULE.value
    assert result["min_valid_date"] in {min_valid_before, min_valid_after}


@pytest.mark.asyncio
async def test_find_next_available_omits_semantic_fields_when_no_substitution_occurs():
    preferred_date = datetime.now(availability_tools_module.MADRID_TZ) + timedelta(days=7)
    stylist = _make_stylist()

    with patch.object(
        availability_tools_module,
        "parse_natural_date",
        return_value=preferred_date,
    ), patch.object(
        availability_tools_module,
        "get_stylists_by_category",
        new=AsyncMock(return_value=[stylist]),
    ), patch.object(
        availability_tools_module,
        "get_next_open_date",
        new=AsyncMock(side_effect=lambda value, max_search_days=14: value),
    ), patch.object(
        availability_tools_module,
        "is_date_closed",
        new=AsyncMock(return_value=False),
    ), patch.object(
        availability_tools_module,
        "is_holiday",
        new=AsyncMock(return_value=None),
    ), patch.object(
        availability_tools_module,
        "get_available_slots",
        new=AsyncMock(
            return_value=[
                {
                    "time": "10:00",
                    "end_time": "11:00",
                    "full_datetime": preferred_date.isoformat(),
                }
            ]
        ),
    ):
        result = await availability_tools_module.find_next_available.ainvoke(
            {
                "service_category": "Peluquería",
                "start_date": "2026-03-30",
                "max_days_to_search": 1,
            }
        )

    assert "substitution_made" not in result
    assert "date_requested" not in result
    assert "date_substituted" not in result
    assert "substitution_reason" not in result
    assert "min_valid_date" not in result


@pytest.mark.asyncio
async def test_check_availability_returns_semantic_fields_when_date_is_too_soon():
    requested_date = datetime.now(availability_tools_module.MADRID_TZ) + timedelta(days=1)
    min_valid_before = (
        datetime.now(availability_tools_module.MADRID_TZ) + timedelta(days=availability_tools_module.MINIMUM_DAYS)
    ).date().isoformat()
    min_valid_after = (
        datetime.now(availability_tools_module.MADRID_TZ) + timedelta(days=availability_tools_module.MINIMUM_DAYS)
    ).date().isoformat()

    with patch.object(
        availability_tools_module,
        "parse_natural_date",
        return_value=requested_date,
    ), patch.object(
        availability_tools_module,
        "validate_3_day_rule",
        new=AsyncMock(return_value={"valid": False, "error_message": "Muy pronto", "days_until_appointment": 1}),
    ):
        result = await availability_tools_module.check_availability.ainvoke(
            {"service_category": "Peluquería", "date": "mañana"}
        )

    assert result["date_too_soon"] is True
    assert result["date_requested"] == requested_date.date().isoformat()
    assert result["min_valid_date"] in {min_valid_before, min_valid_after}
    assert result["substitution_reason"] == InterpretationReason.MINIMUM_DAYS_RULE.value


@pytest.mark.asyncio
async def test_check_availability_omits_semantic_fields_for_valid_date():
    requested_date = datetime.now(availability_tools_module.MADRID_TZ) + timedelta(days=7)
    stylist = _make_stylist()

    with patch.object(
        availability_tools_module,
        "parse_natural_date",
        return_value=requested_date,
    ), patch.object(
        availability_tools_module,
        "validate_3_day_rule",
        new=AsyncMock(return_value={"valid": True}),
    ), patch.object(
        availability_tools_module,
        "is_holiday",
        new=AsyncMock(return_value=None),
    ), patch.object(
        availability_tools_module,
        "get_stylists_by_category",
        new=AsyncMock(return_value=[stylist]),
    ), patch.object(
        availability_tools_module,
        "get_available_slots",
        new=AsyncMock(
            return_value=[
                {
                    "time": "11:00",
                    "end_time": "12:30",
                    "full_datetime": requested_date.isoformat(),
                }
            ]
        ),
    ):
        result = await availability_tools_module.check_availability.ainvoke(
            {"service_category": "Peluquería", "date": "2026-03-30"}
        )

    assert result["date_too_soon"] is False
    assert result["available_slots"]
    assert "date_requested" not in result
    assert "min_valid_date" not in result
