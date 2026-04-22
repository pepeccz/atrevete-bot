"""Unit tests for bounded fallback ranking in availability_service."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agent.services.availability_service import get_next_available_options


@pytest.mark.asyncio
async def test_get_next_available_options_clamps_search_to_seven_days():
    requested_date = date.today() + timedelta(days=5)
    preferred_stylist_id = uuid4()

    with patch(
        "agent.services.availability_service.get_available_slots",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_get_available_slots:
        result = await get_next_available_options(
            requested_date=requested_date,
            service_duration_minutes=60,
            preferred_stylist_id=preferred_stylist_id,
            candidate_stylist_ids=[preferred_stylist_id],
            strategy="same_stylist_then_any",
            max_options=5,
            search_days=20,
        )

    assert result["options"] == []
    assert result["search_days"] == 7
    assert result["max_options"] == 3
    assert result["searched_until"] == (requested_date + timedelta(days=7)).isoformat()
    assert mock_get_available_slots.await_count == 7


@pytest.mark.asyncio
async def test_get_next_available_options_keeps_same_stylist_ranked_first():
    requested_date = date.today() + timedelta(days=5)
    preferred_stylist_id = uuid4()
    alternate_stylist_id = uuid4()

    async def _mock_get_available_slots(stylist_id, target_date, service_duration_minutes):
        if stylist_id == preferred_stylist_id and target_date == requested_date + timedelta(days=3):
            return [
                {
                    "full_datetime": f"{target_date.isoformat()}T10:00:00+01:00",
                    "adjacent_priority": 1,
                }
            ]
        if stylist_id == alternate_stylist_id and target_date == requested_date + timedelta(days=1):
            return [
                {
                    "full_datetime": f"{target_date.isoformat()}T09:00:00+01:00",
                    "adjacent_priority": 0,
                }
            ]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        side_effect=_mock_get_available_slots,
    ):
        result = await get_next_available_options(
            requested_date=requested_date,
            service_duration_minutes=60,
            preferred_stylist_id=preferred_stylist_id,
            candidate_stylist_ids=[preferred_stylist_id, alternate_stylist_id],
            strategy="same_stylist_then_any",
            max_options=3,
            search_days=7,
        )

    assert len(result["options"]) == 2
    assert result["options"][0]["stylist_id"] == str(preferred_stylist_id)
    assert result["options"][0]["rank_reason"].startswith("same_stylist")
    assert result["options"][1]["stylist_id"] == str(alternate_stylist_id)


@pytest.mark.asyncio
async def test_get_next_available_options_any_stylist_prefers_earliest_slot():
    requested_date = date.today() + timedelta(days=5)
    stylist_a = uuid4()
    stylist_b = uuid4()

    async def _mock_get_available_slots(stylist_id, target_date, service_duration_minutes):
        if stylist_id == stylist_a and target_date == requested_date + timedelta(days=3):
            return [
                {
                    "full_datetime": f"{target_date.isoformat()}T12:00:00+01:00",
                    "adjacent_priority": 1,
                }
            ]
        if stylist_id == stylist_b and target_date == requested_date + timedelta(days=1):
            return [
                {
                    "full_datetime": f"{target_date.isoformat()}T09:00:00+01:00",
                    "adjacent_priority": 1,
                }
            ]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        side_effect=_mock_get_available_slots,
    ):
        result = await get_next_available_options(
            requested_date=requested_date,
            service_duration_minutes=60,
            preferred_stylist_id=None,
            candidate_stylist_ids=[stylist_a, stylist_b],
            strategy="any_stylist",
            max_options=3,
            search_days=7,
        )

    assert len(result["options"]) == 2
    assert result["options"][0]["stylist_id"] == str(stylist_b)
    assert result["options"][0]["date_iso"] == (requested_date + timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_get_next_available_options_respects_consent_safe_candidate_bounds():
    requested_date = date.today() + timedelta(days=5)
    preferred_stylist_id = uuid4()
    alternate_stylist_id = uuid4()

    async def _mock_get_available_slots(stylist_id, target_date, service_duration_minutes):
        if stylist_id == preferred_stylist_id and target_date == requested_date + timedelta(days=2):
            return [
                {
                    "full_datetime": f"{target_date.isoformat()}T10:00:00+01:00",
                    "adjacent_priority": 1,
                }
            ]
        if stylist_id == alternate_stylist_id:
            return [
                {
                    "full_datetime": f"{target_date.isoformat()}T09:00:00+01:00",
                    "adjacent_priority": 0,
                }
            ]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        side_effect=_mock_get_available_slots,
    ):
        result = await get_next_available_options(
            requested_date=requested_date,
            service_duration_minutes=60,
            preferred_stylist_id=preferred_stylist_id,
            candidate_stylist_ids=[preferred_stylist_id],
            strategy="same_stylist_then_any",
            max_options=3,
            search_days=7,
        )

    assert len(result["options"]) == 1
    assert result["options"][0]["stylist_id"] == str(preferred_stylist_id)
    assert result["options"][0]["rank_reason"].startswith("same_stylist")


@pytest.mark.asyncio
async def test_get_next_available_options_clamps_result_count_to_three():
    requested_date = date.today() + timedelta(days=5)
    preferred_stylist_id = uuid4()

    async def _mock_get_available_slots(stylist_id, target_date, service_duration_minutes):
        return [
            {
                "full_datetime": f"{target_date.isoformat()}T09:00:00+01:00",
                "adjacent_priority": 0,
            }
        ]

    with patch(
        "agent.services.availability_service.get_available_slots",
        side_effect=_mock_get_available_slots,
    ):
        result = await get_next_available_options(
            requested_date=requested_date,
            service_duration_minutes=60,
            preferred_stylist_id=preferred_stylist_id,
            candidate_stylist_ids=[preferred_stylist_id],
            strategy="same_stylist_then_any",
            max_options=10,
            search_days=7,
        )

    assert result["max_options"] == 3
    assert len(result["options"]) == 3
