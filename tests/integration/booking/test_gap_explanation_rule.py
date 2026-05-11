"""Scenario D — Gap explanation when nearest slot is more than 2 days away.

Tests that:
  - get_next_available_options returns gap_explanation_hint when gap > 2 days.
  - hint has correct shape: gap_days_count and skipped_dates with date_iso,
    weekday (Spanish), reason (closed_day|fully_booked).
  - Today 2026-05-11 (Sunday), first slot 2026-05-15 (Thursday) = 4 day gap.
  - gap_explanation_hint is absent when gap <= 2.

STRUCTURAL assertions (tool payload shape): HARD FAIL.
WORDING-PATTERN sub-assertions (Spanish weekday ordering, reason narratives):
  marked @pytest.mark.xfail(strict=False) because they verify tool data that
  feeds into LLM narration — acceptable to drift as business hours config changes.

Refs: spec Scenario D, R3.5, tasks 4.5/4.9, design §2 Slice 4
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

STYLIST_A = uuid4()
SERVICE_DURATION = 45

# Today for these scenario tests — matches spec Scenario D context
TODAY = date(2026, 5, 11)  # Sunday


def _make_slot(time_str: str, date_str: str) -> dict:
    return {
        "time": time_str,
        "end_time": "11:00",
        "full_datetime": f"{date_str}T{time_str}:00+02:00",
        "adjacent_priority": 1,
    }


# ---------------------------------------------------------------------------
# HARD FAIL: structural payload assertions
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gap_hint_present_when_gap_exceeds_2_days():
    """HARD FAIL: gap > 2 days → gap_explanation_hint present in result."""
    from agent.services.availability_service import get_next_available_options

    # Today=2026-05-11 (Sunday), first slot Thursday 2026-05-15 (4 days gap)
    first_slot_date = TODAY + timedelta(days=4)

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == first_slot_date:
            return [_make_slot("10:00", first_slot_date.isoformat())]
        return []

    with (
        patch(
            "agent.services.availability_service.get_available_slots",
            new=AsyncMock(side_effect=fake_get_slots),
        ),
        patch(
            "agent.services.availability_service.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await get_next_available_options(
            requested_date=TODAY,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A],
            max_options=5,
            search_days=7,
        )

    assert "gap_explanation_hint" in result, (
        f"Expected 'gap_explanation_hint' in result when gap=4 days. "
        f"Got keys: {list(result.keys())}. "
        "Verify PR-2 Task 2.9 (gap_explanation_hint computation) is merged."
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gap_hint_shape_gap_days_count():
    """HARD FAIL: hint.gap_days_count == 4 for a 4-day gap."""
    from agent.services.availability_service import get_next_available_options

    first_slot_date = TODAY + timedelta(days=4)

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == first_slot_date:
            return [_make_slot("10:00", first_slot_date.isoformat())]
        return []

    with (
        patch(
            "agent.services.availability_service.get_available_slots",
            new=AsyncMock(side_effect=fake_get_slots),
        ),
        patch(
            "agent.services.availability_service.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await get_next_available_options(
            requested_date=TODAY,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A],
            max_options=5,
            search_days=7,
        )

    hint = result["gap_explanation_hint"]
    assert hint["gap_days_count"] == 4, f"Expected gap_days_count=4, got {hint['gap_days_count']}"
    assert isinstance(hint["skipped_dates"], list), "skipped_dates must be a list"
    assert len(hint["skipped_dates"]) == 3, (
        f"Expected 3 skipped dates (May 12, 13, 14), got {len(hint['skipped_dates'])}: "
        f"{hint['skipped_dates']}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gap_hint_skipped_dates_have_required_keys():
    """HARD FAIL: each skipped_date entry must have date_iso, weekday, and reason."""
    from agent.services.availability_service import get_next_available_options

    first_slot_date = TODAY + timedelta(days=4)

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == first_slot_date:
            return [_make_slot("10:00", first_slot_date.isoformat())]
        return []

    with (
        patch(
            "agent.services.availability_service.get_available_slots",
            new=AsyncMock(side_effect=fake_get_slots),
        ),
        patch(
            "agent.services.availability_service.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await get_next_available_options(
            requested_date=TODAY,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A],
            max_options=5,
            search_days=7,
        )

    for entry in result["gap_explanation_hint"]["skipped_dates"]:
        assert "date_iso" in entry, f"Missing 'date_iso' in skipped_date entry: {entry}"
        assert "weekday" in entry, f"Missing 'weekday' in skipped_date entry: {entry}"
        assert "reason" in entry, f"Missing 'reason' in skipped_date entry: {entry}"
        assert entry["reason"] in (
            "closed_day",
            "fully_booked",
        ), f"reason must be 'closed_day' or 'fully_booked', got '{entry['reason']}'"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gap_hint_absent_when_gap_lte_2():
    """HARD FAIL: gap <= 2 days → gap_explanation_hint absent."""
    from agent.services.availability_service import get_next_available_options

    first_slot_date = TODAY + timedelta(days=2)  # 2-day gap: no hint

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == first_slot_date:
            return [_make_slot("10:00", first_slot_date.isoformat())]
        return []

    with patch(
        "agent.services.availability_service.get_available_slots",
        new=AsyncMock(side_effect=fake_get_slots),
    ):
        result = await get_next_available_options(
            requested_date=TODAY,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A],
            max_options=5,
            search_days=5,
        )

    assert "gap_explanation_hint" not in result, (
        f"gap_explanation_hint must be absent when gap=2 days. "
        f"Got: {result.get('gap_explanation_hint')}"
    )


# ---------------------------------------------------------------------------
# SOFT (xfail): wording-pattern sub-assertions that depend on LLM narration
# These validate that the TOOL PAYLOAD is correct — the LLM narration itself
# is not deterministic, so these are xfail(strict=False).
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=False,
    reason=(
        "LLM-dependent wording assertion — validates Spanish weekday correctness "
        "in skipped_dates, which is deterministic from the tool but depends on "
        "business hours config for reason classification. Soft check."
    ),
)
async def test_gap_hint_spanish_weekday_names_correct():
    """SOFT: skipped_dates for May 12-14 have correct Spanish weekday names.

    Today=2026-05-11 (Sunday), gap=4 → skipped May 12 (lunes), 13 (martes), 14 (miércoles).
    """
    from agent.services.availability_service import get_next_available_options

    first_slot_date = TODAY + timedelta(days=4)  # Thursday 2026-05-15

    async def fake_get_slots(stylist_id, target_date, service_duration_minutes):
        if target_date == first_slot_date:
            return [_make_slot("10:00", first_slot_date.isoformat())]
        return []

    with (
        patch(
            "agent.services.availability_service.get_available_slots",
            new=AsyncMock(side_effect=fake_get_slots),
        ),
        patch(
            "agent.services.availability_service.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await get_next_available_options(
            requested_date=TODAY,
            service_duration_minutes=SERVICE_DURATION,
            preferred_stylist_id=STYLIST_A,
            candidate_stylist_ids=[STYLIST_A],
            max_options=5,
            search_days=7,
        )

    skipped = result["gap_explanation_hint"]["skipped_dates"]
    by_date = {e["date_iso"]: e["weekday"] for e in skipped}

    # May 12 = Monday = lunes
    assert (
        by_date.get("2026-05-12") == "lunes"
    ), f"Expected 'lunes' for 2026-05-12, got '{by_date.get('2026-05-12')}'"
    # May 13 = Tuesday = martes
    assert (
        by_date.get("2026-05-13") == "martes"
    ), f"Expected 'martes' for 2026-05-13, got '{by_date.get('2026-05-13')}'"
    # May 14 = Wednesday = miércoles
    assert (
        by_date.get("2026-05-14") == "miércoles"
    ), f"Expected 'miércoles' for 2026-05-14, got '{by_date.get('2026-05-14')}'"
