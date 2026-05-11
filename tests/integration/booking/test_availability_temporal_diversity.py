"""Scenario C — Temporal diversity in availability slots (HARD FAIL).

Tests that get_next_available_options deduplicates by start_iso:
  - When 3 stylists all have a slot at the same start_iso, only 1 entry is kept.
  - The retained entry belongs to the highest-priority stylist.
  - Slots at distinct start_iso values are all preserved.

These tests use mock availability (no real DB required). They validate the
dedup pass introduced in PR-2 Task 2.7.

All assertions are HARD FAIL (no xfail).

Refs: spec Scenario C, R2.5-R2.6, tasks 4.4, design §2 Slice 4
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# Three fake stylist UUIDs — STYLIST_A is preferred (phase_priority=0)
STYLIST_A = uuid4()
STYLIST_B = uuid4()
STYLIST_C = uuid4()

SERVICE_DURATION = 45
BASE_DATE = date(2026, 5, 11)  # Monday


def _make_slot(time_str: str, date_str: str) -> dict:
    """Build a slot dict matching get_available_slots output shape."""
    return {
        "time": time_str,
        "end_time": "11:00",
        "full_datetime": f"{date_str}T{time_str}:00+02:00",
        "adjacent_priority": 1,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_three_stylists_same_slot_produces_one_entry():
    """R2.5: 3 stylists sharing a start_iso → exactly 1 entry in returned options."""
    from agent.services.availability_service import get_next_available_options

    search_date = BASE_DATE + timedelta(days=1)  # Tuesday
    shared_slot = _make_slot("10:00", search_date.isoformat())
    shared_start_iso = f"{search_date.isoformat()}T10:00:00+02:00"

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == search_date:
            return [shared_slot]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        new=AsyncMock(side_effect=fake_get_slots),
    ):
        result = await get_next_available_options(
            requested_date=BASE_DATE,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A, STYLIST_B, STYLIST_C],
            max_options=10,
            search_days=3,
        )

    options = result["options"]
    start_isos = [opt["start_iso"] for opt in options]
    count = start_isos.count(shared_start_iso)

    assert count == 1, (
        f"Expected exactly 1 entry for start_iso={shared_start_iso}, got {count}. "
        f"All returned start_isos: {start_isos}. "
        "The PR-2 dedup pass must deduplicate by start_iso before truncation."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retained_entry_is_highest_priority_stylist():
    """R2.5: when dedup fires, the retained entry belongs to the preferred stylist."""
    from agent.services.availability_service import get_next_available_options

    search_date = BASE_DATE + timedelta(days=1)
    shared_slot = _make_slot("10:00", search_date.isoformat())
    shared_start_iso = f"{search_date.isoformat()}T10:00:00+02:00"

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == search_date:
            return [shared_slot]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        new=AsyncMock(side_effect=fake_get_slots),
    ):
        result = await get_next_available_options(
            requested_date=BASE_DATE,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,  # preferred → phase_priority=0
            candidate_stylist_ids=[STYLIST_A, STYLIST_B, STYLIST_C],
            max_options=10,
            search_days=3,
        )

    matching = [opt for opt in result["options"] if opt["start_iso"] == shared_start_iso]
    assert len(matching) == 1, "Expected exactly 1 deduped entry for the shared start_iso"

    retained = matching[0]
    assert retained["stylist_id"] == str(STYLIST_A), (
        f"Expected retained stylist to be STYLIST_A (preferred, phase_priority=0). "
        f"Got stylist_id={retained['stylist_id']}. "
        "Dedup must keep the first entry after priority sort (best phase_priority)."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_dedup_for_distinct_start_isos():
    """Dedup must NOT remove entries with distinct start_iso values."""
    from agent.services.availability_service import get_next_available_options

    search_date = BASE_DATE + timedelta(days=1)

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date != search_date:
            return []
        if stylist_id == STYLIST_A:
            return [_make_slot("10:00", search_date.isoformat())]
        elif stylist_id == STYLIST_B:
            return [_make_slot("11:00", search_date.isoformat())]
        elif stylist_id == STYLIST_C:
            return [_make_slot("14:00", search_date.isoformat())]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        new=AsyncMock(side_effect=fake_get_slots),
    ):
        result = await get_next_available_options(
            requested_date=BASE_DATE,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A, STYLIST_B, STYLIST_C],
            max_options=10,
            search_days=3,
        )

    options = result["options"]
    start_isos = [opt["start_iso"] for opt in options]

    assert len(start_isos) == len(
        set(start_isos)
    ), f"Dedup incorrectly removed distinct start_iso entries: {start_isos}"
    assert (
        len(options) == 3
    ), f"Expected 3 distinct options (one per stylist). Got {len(options)}: {start_isos}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_at_least_two_distinct_datetimes_returned():
    """Returned list includes slots from at least 2 distinct start_iso values when available."""
    from agent.services.availability_service import get_next_available_options

    search_date = BASE_DATE + timedelta(days=1)
    search_date2 = BASE_DATE + timedelta(days=2)

    # STYLIST_A and STYLIST_B share Thursday 10:00; STYLIST_C has Friday 10:00
    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == search_date and stylist_id in (STYLIST_A, STYLIST_B):
            return [_make_slot("10:00", search_date.isoformat())]
        if target_date == search_date2 and stylist_id == STYLIST_C:
            return [_make_slot("10:00", search_date2.isoformat())]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        new=AsyncMock(side_effect=fake_get_slots),
    ):
        result = await get_next_available_options(
            requested_date=BASE_DATE,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A, STYLIST_B, STYLIST_C],
            max_options=10,
            search_days=5,
        )

    options = result["options"]
    distinct_datetimes = {opt["start_iso"] for opt in options}

    assert len(distinct_datetimes) >= 2, (
        f"Expected options from at least 2 distinct start_iso datetimes. "
        f"Got: {distinct_datetimes}. "
        "After dedup, both the shared slot and the unique slot should be present."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_duplicate_start_isos_in_final_result():
    """Final result list must have all unique start_iso values — invariant."""
    from agent.services.availability_service import get_next_available_options

    search_date = BASE_DATE + timedelta(days=1)
    shared_slot = _make_slot("10:00", search_date.isoformat())

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == search_date:
            return [shared_slot]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        new=AsyncMock(side_effect=fake_get_slots),
    ):
        result = await get_next_available_options(
            requested_date=BASE_DATE,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A, STYLIST_B, STYLIST_C],
            max_options=10,
            search_days=3,
        )

    options = result["options"]
    start_isos = [opt["start_iso"] for opt in options]

    # Invariant: no two entries may share a start_iso (spec R2.5)
    assert len(start_isos) == len(
        set(start_isos)
    ), f"start_iso uniqueness invariant violated. Duplicates found in: {start_isos}"
