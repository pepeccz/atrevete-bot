"""
Integration QA scenarios for booking-flow-ux-fixes.

These are structural/contract tests — they verify the tool payload shape
and prompt-guiding fields that the LLM will use to produce correct output.
They do NOT invoke the LLM (that would require Docker + live OpenRouter).

Scenarios:
  5.1 — Óleo disambiguation: payload field for variant check
  5.2 — Lead-time rejection: payload carries rejection reason
  5.3 — Date rendering: slots carry 'label' in Spanish, not ISO format
"""

import json
import re
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

FAKE_SERVICE_ID = uuid4()
FAKE_STYLIST_ID = uuid4()


def future_date_iso(days_ahead: int = 5) -> str:
    return (date.today() + timedelta(days=days_ahead)).isoformat()


def parse(raw: str) -> dict:
    return json.loads(raw)


def _make_slot(date_iso: str, time: str = "10:00") -> dict:
    return {
        "time": time,
        "end_time": "11:00",
        "full_datetime": f"{date_iso}T{time}:00+02:00",
        "stylist_id": str(FAKE_STYLIST_ID),
        "adjacent_priority": 1,
    }


def _settings_service(min_days: int = 0):
    service = AsyncMock()

    async def fake_get(key, default=None):
        if key == "minimum_booking_days_advance":
            return min_days
        if key == "same_day_buffer_hours":
            return 0
        return default

    service.get = fake_get
    return service


# ---------------------------------------------------------------------------
# 5.1 — Variant disambiguation (structural: payload carries service ids)
#
# The actual disambiguation is a prompt/LLM behavior rule. Here we verify
# that when the tool is called with a specific variant's service_id, the
# payload comes back as ok — meaning the LLM would only call the tool
# AFTER the variant was resolved (not before). The "before" state is NOT
# calling the tool, which we cannot test at tool level.
#
# What we CAN assert: once exact variant chosen → tool returns ok with label.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oleo_exact_variant_resolves_to_ok_with_label():
    """
    After óleo disambiguation resolves to exact variant:
    - Tool call succeeds (ok)
    - Each slot has a 'label' in Spanish
    - 'available_stylists' is present
    """
    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)
    fake_slots = [_make_slot(date_iso, "10:00")]

    with (
        patch(
            "shared.settings_service.get_settings_service",
            new_callable=AsyncMock,
            return_value=_settings_service(min_days=0),
        ),
        patch(
            "agent.tools.check_availability.get_available_slots",
            new_callable=AsyncMock,
            return_value=fake_slots,
        ),
        patch(
            "agent.tools.check_availability.get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 90},
        ),
        patch(
            "agent.tools.check_availability.get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[FAKE_STYLIST_ID],
        ),
        patch(
            "agent.tools.check_availability.get_stylist_names_map",
            new_callable=AsyncMock,
            return_value={FAKE_STYLIST_ID: "Ana"},
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],  # exact variant already chosen
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse(raw)
    assert data["status"] == "ok"
    # Slots have Spanish label (Rule 18 compliance)
    slot = data["payload"]["slots"][0]
    assert "label" in slot
    label_pattern = re.compile(r"^[a-záéíóú]+ \d{1,2} de [a-záéíóú]+$")
    assert label_pattern.match(slot["label"]), f"label not Spanish: {slot['label']!r}"
    # available_stylists present (Step 3 reference)
    assert "available_stylists" in data["payload"]
    assert len(data["payload"]["available_stylists"]) >= 1


# ---------------------------------------------------------------------------
# 5.2 — Lead-time rejection scenario
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_time_rejection_carries_human_readable_message():
    """
    When min_days=3 and customer picks tomorrow:
    - Tool returns rejected
    - Error message is human-readable (mentions days / antelación)
    - No book tool would be called (assertion: status != ok)
    """
    from agent.tools.check_availability import check_availability

    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    with (
        patch(
            "shared.settings_service.get_settings_service",
            new_callable=AsyncMock,
            return_value=_settings_service(min_days=3),
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": tomorrow,
                "audience": None,
            }
        )

    data = parse(raw)
    assert data["status"] == "rejected"
    assert len(data["errors"]) > 0
    combined = " ".join(data["errors"]).lower()
    assert "antelación" in combined or "días" in combined, (
        f"Lead-time rejection message not informative: {data['errors']}"
    )


@pytest.mark.asyncio
async def test_lead_time_rejection_at_boundary_minus_1_not_ok():
    """Date at min_days-1 boundary (2 days out, min=3) is rejected."""
    from agent.tools.check_availability import check_availability

    two_days_out = (date.today() + timedelta(days=2)).isoformat()

    with (
        patch(
            "shared.settings_service.get_settings_service",
            new_callable=AsyncMock,
            return_value=_settings_service(min_days=3),
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": two_days_out,
                "audience": None,
            }
        )

    data = parse(raw)
    assert data["status"] == "rejected"


# ---------------------------------------------------------------------------
# 5.3 — Date rendering: slots carry label in Spanish, not ISO format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_date_rendering_label_not_iso():
    """
    Slots must carry 'label' in Spanish weekday+day+month format.
    The label must NOT match an ISO date pattern (YYYY-MM-DD).
    The top-level requested_date_label must also be Spanish format.
    """
    from agent.tools.check_availability import check_availability

    date_iso = future_date_iso(5)
    fake_slots = [_make_slot(date_iso, "10:00"), _make_slot(date_iso, "12:00")]

    with (
        patch(
            "shared.settings_service.get_settings_service",
            new_callable=AsyncMock,
            return_value=_settings_service(min_days=0),
        ),
        patch(
            "agent.tools.check_availability.get_available_slots",
            new_callable=AsyncMock,
            return_value=fake_slots,
        ),
        patch(
            "agent.tools.check_availability.get_service_durations",
            new_callable=AsyncMock,
            return_value={FAKE_SERVICE_ID: 60},
        ),
        patch(
            "agent.tools.check_availability.get_active_stylists_for_services",
            new_callable=AsyncMock,
            return_value=[FAKE_STYLIST_ID],
        ),
        patch(
            "agent.tools.check_availability.get_stylist_names_map",
            new_callable=AsyncMock,
            return_value={FAKE_STYLIST_ID: "Ana"},
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [str(FAKE_SERVICE_ID)],
                "stylist_id": None,
                "date_iso": date_iso,
                "audience": None,
            }
        )

    data = parse(raw)
    assert data["status"] == "ok"

    iso_pattern = re.compile(r"\d{4}-\d{2}-\d{2}")
    spanish_pattern = re.compile(r"^[a-záéíóú]+ \d{1,2} de [a-záéíóú]+$")

    # Every slot label is Spanish, not ISO
    for slot in data["payload"]["slots"]:
        label = slot["label"]
        assert not iso_pattern.match(label), f"slot label looks like ISO: {label!r}"
        assert spanish_pattern.match(label), f"slot label not Spanish: {label!r}"

    # Top-level requested_date_label is Spanish
    rdl = data["payload"]["requested_date_label"]
    assert not iso_pattern.match(rdl), f"requested_date_label looks like ISO: {rdl!r}"
    assert spanish_pattern.match(rdl), f"requested_date_label not Spanish: {rdl!r}"
