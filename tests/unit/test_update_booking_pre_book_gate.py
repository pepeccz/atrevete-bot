"""T5 — update_booking pre_book_validation_required gate.

Tests spec R2.1, R2.2, R2.3, R2.5 / ADR-6.

Post-PR#2: patches target BookingQueryService.resolve_all and
BookingQueryService.resolve_audience_variants instead of _booking_helpers.* functions.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

FAKE_SERVICE_ID = str(uuid4())
FAKE_STYLIST_ID = str(uuid4())
FAKE_DATE = (date.today() + timedelta(days=10)).isoformat()


def _make_resolve_all(stylist_id=None):
    """Build a ResolveAllResult for mocking BookingQueryService.resolve_all."""
    from agent.services.booking_query_service import ResolveAllResult

    sid = stylist_id or FAKE_STYLIST_ID
    return ResolveAllResult(
        success=True,
        service_ids=[FAKE_SERVICE_ID],
        unknown_names=[],
        stylist_id=sid,
        audience_variants=("none", "", []),
        categories=set(),
        id_to_category={},
        active_stylists=[],
        has_category_mix=False,
        hair_services=[],
        aesth_services=[],
        both_services=[],
        error_message=None,
    )


def _build_check_avail_tool_message(
    slot_datetime: str = None,
    stylist_id: str = None,
    status: str = "ok",
) -> object:
    """Build a fake ToolMessage that looks like a check_availability result."""
    slot_dt = slot_datetime or f"{FAKE_DATE}T10:00:00+02:00"
    sid = stylist_id or FAKE_STYLIST_ID

    msg = MagicMock()
    msg.name = "check_availability"
    msg.content = json.dumps({
        "status": status,
        "payload": {
            "slots": [{"start_iso": slot_dt, "stylist_id": sid}],
            "exact_match": True,
        },
    })
    return msg


async def _call_impl(slot_iso, messages=None, stylist_id=None, **extra):
    """Call _update_booking_impl with standard mocks for all gates."""
    from agent.tools.update_booking import _update_booking_impl

    resolve_all_result = _make_resolve_all(stylist_id=stylist_id)

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            new=AsyncMock(return_value=resolve_all_result),
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        result_json = await _update_booking_impl(
            services=["corte"],
            stylist_name="Marta",
            no_preference_stylist=False,
            date_iso=FAKE_DATE,
            audience=None,
            customer_full_name="Juan García",
            notes=None,
            no_more_services=True,
            extras_asked=True,
            notes_asked=True,
            customer_known=True,
            slot_iso=slot_iso,
            messages=messages or [],
            **extra,
        )

    return json.loads(result_json)


@pytest.mark.asyncio
async def test_booking_ready_blocked_without_pre_book_validation():
    """notes_asked=True but no check_availability ToolMessage → pre_book_validation_required."""
    result = await _call_impl(
        slot_iso=f"{FAKE_DATE}T10:00:00+02:00",
        messages=[],  # No recent messages → no check_availability ToolMessage
    )
    assert result["next_step"] == "pre_book_validation_required", (
        f"Expected pre_book_validation_required, got: {result}"
    )


@pytest.mark.asyncio
async def test_booking_ready_unblocked_with_matching_validation():
    """Matching check_availability ToolMessage present → advances to booking_ready."""
    slot_dt = f"{FAKE_DATE}T10:00:00+02:00"
    stylist_uuid = str(uuid4())

    tool_msg = _build_check_avail_tool_message(
        slot_datetime=slot_dt,
        stylist_id=stylist_uuid,
    )

    result = await _call_impl(
        slot_iso=slot_dt,
        messages=[tool_msg],
        stylist_id=stylist_uuid,
    )
    assert result["next_step"] == "booking_ready", (
        f"Expected booking_ready, got: {result}"
    )


@pytest.mark.asyncio
async def test_booking_ready_blocked_mismatched_slot():
    """ToolMessage present but different slot → stays pre_book_validation_required."""
    slot_dt = f"{FAKE_DATE}T10:00:00+02:00"
    different_slot_dt = f"{FAKE_DATE}T14:00:00+02:00"
    stylist_uuid = str(uuid4())

    # Message confirms 10:00 but booking is for 14:00
    tool_msg = _build_check_avail_tool_message(
        slot_datetime=slot_dt,
        stylist_id=stylist_uuid,
    )

    result = await _call_impl(
        slot_iso=different_slot_dt,  # different from tool_msg
        messages=[tool_msg],
        stylist_id=stylist_uuid,
    )
    assert result["next_step"] == "pre_book_validation_required", (
        f"Expected pre_book_validation_required for mismatched slot, got: {result}"
    )
