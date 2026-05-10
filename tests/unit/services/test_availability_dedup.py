"""RED test — Task 2.6: get_next_available_options start_iso deduplication.

Asserts that when multiple stylists all have a free slot at the same start_iso,
the function returns exactly ONE entry for that start_iso, not one per stylist.
The retained entry must be the one with the best _priority (lowest phase_priority).

Tests FAIL before Task 2.7 implements the dedup pass.

Refs: design §2 Slice 2, spec R2.5-R2.6, task 2.6/2.7
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# Three fake stylist IDs — the phase_priority order matters for dedup selection
STYLIST_A = uuid4()  # preferred → phase_priority=0 (first phase)
STYLIST_B = uuid4()  # alternate → phase_priority=1
STYLIST_C = uuid4()  # alternate → phase_priority=1

SERVICE_DURATION = 45


def _make_slot(time_str: str, date_str: str) -> dict:
    """Build a slot dict matching availability_service.get_available_slots shape."""
    return {
        "time": time_str,
        "end_time": "11:00",
        "full_datetime": f"{date_str}T{time_str}:00+02:00",
        "adjacent_priority": 1,
    }


@pytest.mark.asyncio
async def test_three_stylists_same_start_iso_produces_one_slot():
    """R2.5: three stylists all free at same start_iso → exactly 1 entry in options."""
    from agent.services.availability_service import get_next_available_options

    base_date = date(2026, 5, 11)  # Monday
    search_date = base_date + timedelta(days=1)  # Tuesday 2026-05-12
    shared_start_iso = f"{search_date.isoformat()}T10:00:00+02:00"

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
            requested_date=base_date,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A, STYLIST_B, STYLIST_C],
            max_options=10,
            search_days=3,
        )

    options = result["options"]
    start_isos = [opt["start_iso"] for opt in options]

    # The shared start_iso must appear exactly once
    count = start_isos.count(shared_start_iso)
    assert count == 1, (
        f"Expected 1 entry for start_iso={shared_start_iso}, got {count}. "
        f"All start_isos: {start_isos}. "
        "Task 2.7 dedup pass is needed."
    )


@pytest.mark.asyncio
async def test_deduplicated_slot_is_highest_priority_stylist():
    """R2.5: when dedup fires, the retained entry belongs to the highest-priority stylist."""
    from agent.services.availability_service import get_next_available_options

    base_date = date(2026, 5, 11)
    search_date = base_date + timedelta(days=1)
    shared_start_iso = f"{search_date.isoformat()}T10:00:00+02:00"
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
            requested_date=base_date,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,          # STYLIST_A is preferred → phase_priority=0
            candidate_stylist_ids=[STYLIST_A, STYLIST_B, STYLIST_C],
            max_options=10,
            search_days=3,
        )

    options = result["options"]
    matching = [opt for opt in options if opt["start_iso"] == shared_start_iso]
    assert len(matching) == 1

    # The retained entry must belong to STYLIST_A (phase_priority=0)
    retained = matching[0]
    assert retained["stylist_id"] == str(STYLIST_A), (
        f"Expected retained stylist to be STYLIST_A ({STYLIST_A}), "
        f"got {retained['stylist_id']}. "
        "Dedup must keep the first (best phase_priority) entry."
    )


@pytest.mark.asyncio
async def test_different_start_isos_not_deduped():
    """Dedup must not remove entries with DISTINCT start_iso values."""
    from agent.services.availability_service import get_next_available_options

    base_date = date(2026, 5, 11)
    search_date = base_date + timedelta(days=1)

    # Each stylist has a DIFFERENT time slot
    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == search_date:
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
            requested_date=base_date,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A, STYLIST_B, STYLIST_C],
            max_options=10,
            search_days=3,
        )

    options = result["options"]
    start_isos = [opt["start_iso"] for opt in options]

    # All three distinct start_isos must be present
    assert len(start_isos) == len(set(start_isos)), (
        f"Distinct start_isos were deduped incorrectly: {start_isos}"
    )
    assert len(options) == 3, f"Expected 3 distinct options, got {len(options)}: {start_isos}"


@pytest.mark.asyncio
async def test_single_stylist_same_start_iso_dedup_fires():
    """R2.6: dedup applies even for a single stylist — duplicate start_isos within one stylist."""
    from agent.services.availability_service import get_next_available_options

    base_date = date(2026, 5, 11)
    search_date = base_date + timedelta(days=1)

    # Return two identical slots (edge case — normally shouldn't happen, but must be safe)
    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == search_date:
            return [
                _make_slot("10:00", search_date.isoformat()),
                _make_slot("10:00", search_date.isoformat()),  # duplicate
            ]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        new=AsyncMock(side_effect=fake_get_slots),
    ):
        result = await get_next_available_options(
            requested_date=base_date,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A],
            max_options=10,
            search_days=3,
        )

    options = result["options"]
    start_isos = [opt["start_iso"] for opt in options]

    # Must deduplicate: only 1 entry for the duplicate start_iso
    assert len(start_isos) == len(set(start_isos)), (
        f"Duplicate start_iso was not removed: {start_isos}"
    )
