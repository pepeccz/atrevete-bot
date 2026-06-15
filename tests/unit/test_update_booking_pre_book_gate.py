"""T5 — update_booking pre_book_validation_required gate.

Tests spec R2.1, R2.2, R2.3, R2.5 / ADR-6.

Migrated (T4): patches on _get_recent_messages replaced with messages= kwarg
passed directly to _update_booking_impl.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

FAKE_SERVICE_ID = str(uuid4())
FAKE_STYLIST_ID = str(uuid4())
FAKE_DATE = (date.today() + timedelta(days=5)).isoformat()


def _make_ok_fk():
    r = MagicMock()
    r.ok = True
    r.missing_ids = []
    r.payload = {}
    return r


def _base_patches(
    resolved_ids=None,
    stylist_id=None,
    is_closed=False,
):
    resolved_ids = resolved_ids or [FAKE_SERVICE_ID]
    return {
        "agent.tools._booking_helpers._resolve_service_ids": AsyncMock(
            return_value=(resolved_ids, [])
        ),
        "agent.tools._booking_helpers._resolve_service_ids_strict": AsyncMock(
            return_value=(resolved_ids, [], [], [])
        ),
        "agent.tools._booking_helpers._resolve_service_categories": AsyncMock(
            return_value=set()
        ),
        "agent.tools._booking_helpers._resolve_audience_variants": AsyncMock(
            return_value=("none", None, [])
        ),
        "agent.tools._booking_helpers._resolve_stylist": AsyncMock(
            return_value=uuid4() if stylist_id is None else stylist_id
        ),
        "agent.tools._booking_helpers._resolve_active_stylists": AsyncMock(return_value=[]),
        "agent.tools._booking_helpers._resolve_service_id_to_category_map": AsyncMock(
            return_value={}
        ),
        "agent.tools._booking_helpers._validate_full_name": MagicMock(
            return_value=("Juan", "García")
        ),
        "shared.business_hours_validator.is_date_closed": AsyncMock(return_value=is_closed),
        "agent.tools._booking_validators.is_date_closed": AsyncMock(return_value=is_closed),
        "agent.tools.update_booking.validate_service_ids_exist": AsyncMock(return_value=_make_ok_fk()),
        "agent.tools.update_booking.validate_stylist_id_exists": AsyncMock(return_value=_make_ok_fk()),
        "agent.tools.update_booking._load_lead_time_min_days": AsyncMock(return_value=3),
    }


def _build_check_avail_tool_message(
    slot_datetime: str = None,
    stylist_id: str = None,
    status: str = "ok",
) -> object:
    """Build a fake ToolMessage that looks like a check_availability result."""
    from unittest.mock import MagicMock

    slot_dt = slot_datetime or f"{FAKE_DATE}T10:00:00+02:00"
    sid = stylist_id or FAKE_STYLIST_ID

    msg = MagicMock()
    msg.name = "check_availability"
    msg.content = json.dumps({
        "status": status,
        "payload": {
            "slots": [
                {
                    "start_iso": slot_dt,
                    "stylist_id": sid,
                }
            ],
            "exact_match": True,
        },
    })
    return msg


def _make_session_ctx():
    session_mock = AsyncMock()
    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=session_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)
    return ctx_mock


@pytest.mark.asyncio
async def test_booking_ready_blocked_without_pre_book_validation():
    """notes_asked=True but no check_availability ToolMessage → pre_book_validation_required."""
    from agent.tools.update_booking import _update_booking_impl

    patches = _base_patches(stylist_id=FAKE_STYLIST_ID)
    ctx = _make_session_ctx()

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            patches["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            patches["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            patches["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            patches["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            patches["agent.tools._booking_helpers._resolve_stylist"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            patches["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            patches["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            patches["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            patches["shared.business_hours_validator.is_date_closed"],
        ),
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools._booking_validators.is_date_closed", patches["agent.tools._booking_validators.is_date_closed"]),
        patch("agent.tools.update_booking.validate_service_ids_exist", patches["agent.tools.update_booking.validate_service_ids_exist"]),
        patch("agent.tools.update_booking.validate_stylist_id_exists", patches["agent.tools.update_booking.validate_stylist_id_exists"]),
        patch("agent.tools.update_booking._load_lead_time_min_days", patches["agent.tools.update_booking._load_lead_time_min_days"]),
    ):
        _slot_iso = f"{FAKE_DATE}T10:00:00+02:00"
        from datetime import UTC, datetime, timedelta
        _expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        _offered = [{"start_iso": _slot_iso, "stylist_id": FAKE_STYLIST_ID, "expires_at": _expires, "turn_index": 0}]
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
            slot_iso=_slot_iso,  # slot_iso activates the gate
            recently_offered_slots=_offered,
            messages=[],  # No recent messages → no check_availability ToolMessage
            policy_accepted=True,
        )

    result = json.loads(result_json)
    assert result["next_step"] == "pre_book_validation_required", (
        f"Expected pre_book_validation_required, got: {result}"
    )


@pytest.mark.asyncio
async def test_booking_ready_unblocked_with_matching_validation():
    """Matching check_availability ToolMessage present → advances to booking_ready."""
    from agent.tools.update_booking import _update_booking_impl

    slot_dt = f"{FAKE_DATE}T10:00:00+02:00"
    stylist_uuid = str(uuid4())
    patches = _base_patches(stylist_id=stylist_uuid)
    ctx = _make_session_ctx()

    tool_msg = _build_check_avail_tool_message(
        slot_datetime=slot_dt,
        stylist_id=stylist_uuid,
    )

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            patches["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            patches["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            patches["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            patches["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            AsyncMock(return_value=stylist_uuid),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            patches["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            patches["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            patches["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            patches["shared.business_hours_validator.is_date_closed"],
        ),
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools._booking_validators.is_date_closed", patches["agent.tools._booking_validators.is_date_closed"]),
        patch("agent.tools.update_booking.validate_service_ids_exist", patches["agent.tools.update_booking.validate_service_ids_exist"]),
        patch("agent.tools.update_booking.validate_stylist_id_exists", patches["agent.tools.update_booking.validate_stylist_id_exists"]),
        patch("agent.tools.update_booking._load_lead_time_min_days", patches["agent.tools.update_booking._load_lead_time_min_days"]),
    ):
        from datetime import UTC, datetime, timedelta
        _expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        _offered = [{"start_iso": slot_dt, "stylist_id": stylist_uuid, "expires_at": _expires, "turn_index": 0}]
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
            slot_iso=slot_dt,
            recently_offered_slots=_offered,
            messages=[tool_msg],  # Matching ToolMessage present
            policy_accepted=True,
        )

    result = json.loads(result_json)
    assert result["next_step"] == "booking_ready", (
        f"Expected booking_ready, got: {result}"
    )


@pytest.mark.asyncio
async def test_booking_ready_blocked_mismatched_slot():
    """ToolMessage present but different slot → stays pre_book_validation_required."""
    from agent.tools.update_booking import _update_booking_impl

    slot_dt = f"{FAKE_DATE}T10:00:00+02:00"
    different_slot_dt = f"{FAKE_DATE}T14:00:00+02:00"
    stylist_uuid = str(uuid4())
    patches = _base_patches(stylist_id=stylist_uuid)
    ctx = _make_session_ctx()

    # Message confirms 10:00 but booking is for 14:00
    tool_msg = _build_check_avail_tool_message(
        slot_datetime=slot_dt,
        stylist_id=stylist_uuid,
    )

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            patches["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            patches["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            patches["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            patches["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            AsyncMock(return_value=stylist_uuid),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            patches["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            patches["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            patches["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            patches["shared.business_hours_validator.is_date_closed"],
        ),
        patch("database.connection.get_async_session", return_value=ctx),
        patch("agent.tools._booking_validators.is_date_closed", patches["agent.tools._booking_validators.is_date_closed"]),
        patch("agent.tools.update_booking.validate_service_ids_exist", patches["agent.tools.update_booking.validate_service_ids_exist"]),
        patch("agent.tools.update_booking.validate_stylist_id_exists", patches["agent.tools.update_booking.validate_stylist_id_exists"]),
        patch("agent.tools.update_booking._load_lead_time_min_days", patches["agent.tools.update_booking._load_lead_time_min_days"]),
    ):
        from datetime import UTC, datetime, timedelta
        _expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        # Offer different_slot_dt so J3 guard passes — the CA mismatch is what we test
        _offered = [{"start_iso": different_slot_dt, "stylist_id": stylist_uuid, "expires_at": _expires, "turn_index": 0}]
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
            slot_iso=different_slot_dt,  # different from tool_msg
            recently_offered_slots=_offered,
            messages=[tool_msg],
            policy_accepted=True,
        )

    result = json.loads(result_json)
    assert result["next_step"] == "pre_book_validation_required", (
        f"Expected pre_book_validation_required for mismatched slot, got: {result}"
    )
