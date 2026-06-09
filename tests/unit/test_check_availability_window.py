"""TDD tests: T5 — preferred_window parameter on check_availability.

Covers AS15 (preferred_window in schema), AS16 (afternoon filter), E3 (glossary mappings).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROMPTS_DIR = Path(__file__).parents[2] / "agent" / "prompts" / "shared"
GLOSSARY = PROMPTS_DIR / "glossary.md"
TOOLS_CONTRACT = PROMPTS_DIR / "tools_contract.md"


# ---------------------------------------------------------------------------
# AS15 — preferred_window field exists in check_availability schema
# ---------------------------------------------------------------------------


def test_preferred_window_field_in_schema():
    """AS15: check_availability tool must accept preferred_window as optional parameter."""
    import inspect

    from agent.tools.check_availability import check_availability

    sig = inspect.signature(check_availability.coroutine if hasattr(check_availability, "coroutine") else check_availability.func)
    params = sig.parameters

    assert "preferred_window" in params, (
        f"check_availability must have a 'preferred_window' parameter. "
        f"Current params: {list(params.keys())}"
    )

    # Must have a default of None (optional)
    assert params["preferred_window"].default is None, (
        "preferred_window must default to None (optional)"
    )


# ---------------------------------------------------------------------------
# AS16 — Afternoon filter: 09:00 slot excluded, 14:00 and 18:00 included
# ---------------------------------------------------------------------------


def _make_slot(time_str: str, stylist_id: str = "aaaa-bbbb") -> dict:
    """Build a minimal slot dict with a Madrid-time ISO datetime."""
    return {
        "full_datetime": f"2026-06-15T{time_str}:00+02:00",  # Europe/Madrid summer (+02:00)
        "stylist_name": "Marta",
        "stylist_id": stylist_id,
        "adjacent_priority": 1,
    }


@pytest.fixture
def mock_availability_deps():
    """Patch all external calls in check_availability so tests run without DB."""
    import uuid

    fake_stylist_uuid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    fake_service_uuid = uuid.UUID("11111111-2222-3333-4444-555555555555")

    with (
        patch("agent.tools.check_availability._load_lead_time_settings", return_value=(0, 0)),
        patch(
            "agent.tools.check_availability._get_service_durations",
            return_value={fake_service_uuid: 60},
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            return_value=[fake_stylist_uuid],
        ),
        patch(
            "agent.tools.check_availability._get_stylist_names_map",
            return_value={fake_stylist_uuid: "Marta"},
        ),
    ):
        yield fake_stylist_uuid, fake_service_uuid


@pytest.mark.asyncio
async def test_afternoon_filter_excludes_morning_slots(mock_availability_deps):
    """AS16: preferred_window='afternoon' must exclude slots before 14:00 Madrid time."""
    import json

    fake_stylist_uuid, fake_service_uuid = mock_availability_deps

    # Slots at 09:00, 14:00, 18:00 Madrid time
    fake_slots = [
        _make_slot("09:00"),   # morning → should be excluded
        _make_slot("14:00"),   # afternoon → included
        _make_slot("18:00"),   # afternoon → included
    ]

    with patch(
        "agent.tools.check_availability.get_available_slots",
        new_callable=AsyncMock,
        return_value=fake_slots,
    ):
        from agent.tools.check_availability import check_availability

        result_json = await check_availability.coroutine(
            service_ids=[str(fake_service_uuid)],
            stylist_id=None,
            date_iso="2026-06-15",
            no_preference=True,
            preferred_window="afternoon",
        )

    result = json.loads(result_json)
    slots = result.get("payload", {}).get("slots", [])
    times = [s["start_iso"][11:16] for s in slots]  # extract HH:MM

    assert "09:00" not in times, f"09:00 slot must be excluded by afternoon filter. Got: {times}"
    assert "14:00" in times, f"14:00 slot must be included in afternoon window. Got: {times}"
    assert "18:00" in times, f"18:00 slot must be included in afternoon window. Got: {times}"


@pytest.mark.asyncio
async def test_morning_filter_excludes_afternoon_slots(mock_availability_deps):
    """AS16: preferred_window='morning' must exclude slots at 14:00+ Madrid time."""
    import json

    fake_stylist_uuid, fake_service_uuid = mock_availability_deps

    fake_slots = [
        _make_slot("09:00"),   # morning → included
        _make_slot("11:00"),   # morning → included
        _make_slot("15:00"),   # afternoon → excluded
    ]

    with patch(
        "agent.tools.check_availability.get_available_slots",
        new_callable=AsyncMock,
        return_value=fake_slots,
    ):
        from agent.tools.check_availability import check_availability

        result_json = await check_availability.coroutine(
            service_ids=[str(fake_service_uuid)],
            stylist_id=None,
            date_iso="2026-06-15",
            no_preference=True,
            preferred_window="morning",
        )

    result = json.loads(result_json)
    slots = result.get("payload", {}).get("slots", [])
    times = [s["start_iso"][11:16] for s in slots]

    assert "15:00" not in times, f"15:00 slot must be excluded by morning filter. Got: {times}"
    assert "09:00" in times, f"09:00 slot must be included in morning window. Got: {times}"
    assert "11:00" in times, f"11:00 slot must be included in morning window. Got: {times}"


@pytest.mark.asyncio
async def test_none_window_returns_all_slots(mock_availability_deps):
    """preferred_window=None must return all slots (no filter)."""
    import json

    fake_stylist_uuid, fake_service_uuid = mock_availability_deps

    fake_slots = [
        _make_slot("09:00"),
        _make_slot("14:00"),
        _make_slot("18:00"),
    ]

    with patch(
        "agent.tools.check_availability.get_available_slots",
        new_callable=AsyncMock,
        return_value=fake_slots,
    ):
        from agent.tools.check_availability import check_availability

        result_json = await check_availability.coroutine(
            service_ids=[str(fake_service_uuid)],
            stylist_id=None,
            date_iso="2026-06-15",
            no_preference=True,
            preferred_window=None,
        )

    result = json.loads(result_json)
    slots = result.get("payload", {}).get("slots", [])
    assert len(slots) == 3, f"None window must return all 3 slots. Got: {len(slots)}"


# ---------------------------------------------------------------------------
# E3 — glossary.md has preferred_window mapping table
# ---------------------------------------------------------------------------


def test_glossary_has_preferred_window_table():
    """E3: glossary.md must contain preferred_window mappings including 'muy tarde' and 'atardecer'."""
    content = GLOSSARY.read_text(encoding="utf-8").lower()

    assert "preferred_window" in content, (
        "glossary.md must contain a preferred_window section"
    )
    assert "morning" in content, "glossary.md must map some phrases to 'morning'"
    assert "afternoon" in content, "glossary.md must map some phrases to 'afternoon'"
    # muy tarde and atardecer must explicitly map to afternoon (not evening)
    assert "muy tarde" in content, "glossary.md must explicitly list 'muy tarde' mapping"
    assert "atardecer" in content, "glossary.md must explicitly list 'atardecer' mapping"
