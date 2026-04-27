"""T-08, T-09 — update_booking: variant gate audience-independence + stylist payload.

RED phase: tests for:
- T-08: variant gate fires even when audience is already known
- T-09: stylist_required emits payload with stylists list + first_available_label
"""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

_MADRID_TZ = ZoneInfo("Europe/Madrid")


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


def _make_session_ctx():
    session_mock = AsyncMock()
    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=session_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)
    return ctx_mock, session_mock


async def _call_update_booking(**kwargs) -> dict:
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke(kwargs)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# T-08: Variant gate fires regardless of audience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_variant_gate_fires_with_known_audience():
    """Audience already set + service is principal with active variants → variant_required fired.

    The variant check must NOT be nested inside 'if audience is None'.
    """
    ctx, _ = _make_session_ctx()

    from database.models import ServiceCategory

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["service-uuid-1"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(
                return_value=("variant", "Peinado", ["Peinado", "Peinado Novia", "Peinado Fiesta"])
            ),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(return_value={ServiceCategory.HAIRDRESSING}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            new=AsyncMock(return_value=None),
        ),
    ):
        # audience IS already set — the variant gate must still fire
        data = await _call_update_booking(
            services=["Peinado"],
            audience="adult_female",  # audience known
        )

    assert data["next_step"] == "variant_required", (
        f"Expected 'variant_required' when audience known but service is principal with variants, "
        f"got '{data['next_step']}'"
    )
    assert data.get("payload", {}).get("variants") is not None


# ---------------------------------------------------------------------------
# T-09: Stylist payload on stylist_required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stylist_required_payload_populated():
    """Active stylists in DB → stylist_required emits payload.stylists non-empty."""
    ctx, _ = _make_session_ctx()

    active_first_names = ["Ana", "Marta", "Pilar"]

    from database.models import ServiceCategory

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["service-uuid-1"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(return_value={ServiceCategory.HAIRDRESSING}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            new=AsyncMock(return_value=active_first_names),
        ),
    ):
        data = await _call_update_booking(
            services=["Corte Dama"],
            no_more_services=True,
            extras_asked=True,
        )

    assert data["next_step"] == "stylist_required", (
        f"Expected 'stylist_required', got '{data['next_step']}'"
    )
    payload = data.get("payload", {})
    assert payload.get("stylists") == active_first_names, (
        f"payload.stylists should be {active_first_names}, got {payload.get('stylists')}"
    )
    label = payload.get("first_available_label", "")
    assert "primera" in label.lower() or "disponibilidad" in label.lower(), (
        f"first_available_label missing proximity hint: {label!r}"
    )


# ---------------------------------------------------------------------------
# Helpers for lead-time gate tests
# ---------------------------------------------------------------------------

_FAKE_STYLIST_ID_LT = "aabbccdd-0001-0002-0003-000000000001"
_FAKE_SERVICE_ID_LT = "aabbccdd-0001-0002-0003-000000000002"


def _lt_patches(is_date_closed_return: bool = False) -> dict:
    """Standard patch dict that gets past Steps 1-5 (service/stylist resolution)."""
    from database.models import ServiceCategory

    return {
        "agent.tools._booking_helpers._resolve_service_ids": AsyncMock(
            return_value=([_FAKE_SERVICE_ID_LT], [])
        ),
        "agent.tools._booking_helpers._resolve_service_categories": AsyncMock(
            return_value={ServiceCategory.HAIRDRESSING}
        ),
        "agent.tools._booking_helpers._resolve_service_id_to_category_map": AsyncMock(
            return_value={}
        ),
        "agent.tools._booking_helpers._resolve_audience_variants": AsyncMock(
            return_value=("ok", None, [])
        ),
        "agent.tools._booking_helpers._resolve_stylist": AsyncMock(
            return_value=_FAKE_STYLIST_ID_LT
        ),
        "agent.tools._booking_helpers._resolve_active_stylists": AsyncMock(
            return_value=[{"id": _FAKE_STYLIST_ID_LT, "name": "Test Stylist"}]
        ),
        "agent.tools._booking_helpers._validate_full_name": MagicMock(return_value=None),
        "database.connection.get_async_session": MagicMock(
            return_value=_make_fake_session_ctx()
        ),
        "shared.business_hours_validator.is_date_closed": AsyncMock(
            return_value=is_date_closed_return
        ),
    }


def _make_fake_session_ctx():
    fake_session = AsyncMock()
    fake_cm = AsyncMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_session)
    fake_cm.__aexit__ = AsyncMock(return_value=False)
    return fake_cm


async def _call_impl(date_iso, patches_override=None, **extra_kwargs):
    from agent.tools.update_booking import _update_booking_impl

    patches = _lt_patches()
    if patches_override:
        patches.update(patches_override)

    with (
        patch("agent.tools._booking_helpers._resolve_service_ids", patches["agent.tools._booking_helpers._resolve_service_ids"]),
        patch("agent.tools._booking_helpers._resolve_service_categories", patches["agent.tools._booking_helpers._resolve_service_categories"]),
        patch("agent.tools._booking_helpers._resolve_service_id_to_category_map", patches["agent.tools._booking_helpers._resolve_service_id_to_category_map"]),
        patch("agent.tools._booking_helpers._resolve_audience_variants", patches["agent.tools._booking_helpers._resolve_audience_variants"]),
        patch("agent.tools._booking_helpers._resolve_stylist", patches["agent.tools._booking_helpers._resolve_stylist"]),
        patch("agent.tools._booking_helpers._resolve_active_stylists", patches["agent.tools._booking_helpers._resolve_active_stylists"]),
        patch("agent.tools._booking_helpers._validate_full_name", patches["agent.tools._booking_helpers._validate_full_name"]),
        patch("database.connection.get_async_session", patches["database.connection.get_async_session"]),
        patch("shared.business_hours_validator.is_date_closed", patches["shared.business_hours_validator.is_date_closed"]),
    ):
        raw = await _update_booking_impl(
            services=["Corte Dama"],
            stylist_name="Test Stylist",
            no_preference_stylist=False,
            date_iso=date_iso,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=True,
            extras_asked=True,
            **extra_kwargs,
        )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# T-LT-01: date below MIN_BOOKING_DAYS → advance_policy_violated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_time_gate_rejects_below_min():
    """T-LT-01 (R1/S1/S5/S6): date_iso = today+2 (below 3-day threshold) → rejected.

    Asserts:
    - next_step == "advance_policy_violated"
    - payload has rejected_date, first_valid_date, policy_min_days, stylist_id, service_ids
    - first_valid_date == today + 3
    """
    from datetime import datetime

    today = datetime.now(_MADRID_TZ).date()
    rejected_date = (today + timedelta(days=2)).isoformat()
    expected_first_valid = (today + timedelta(days=3)).isoformat()

    data = await _call_impl(date_iso=rejected_date)

    assert data["next_step"] == "advance_policy_violated", (
        f"Expected 'advance_policy_violated', got '{data['next_step']}'"
    )
    payload = data.get("payload", {})
    assert payload.get("rejected_date") == rejected_date, f"rejected_date mismatch: {payload}"
    assert payload.get("first_valid_date") == expected_first_valid, f"first_valid_date mismatch: {payload}"
    assert payload.get("policy_min_days") == 3, f"policy_min_days mismatch: {payload}"
    assert "stylist_id" in payload, f"stylist_id missing from payload: {payload}"
    assert "service_ids" in payload, f"service_ids missing from payload: {payload}"


# ---------------------------------------------------------------------------
# T-LT-02: date at exact MIN_BOOKING_DAYS boundary → gate passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_time_gate_passes_at_min():
    """T-LT-02 (R2/S2/R4): date_iso = today+3 (boundary inclusive) → gate passes.

    Execution should continue past lead-time gate to name_required (since no name given).
    """
    from datetime import datetime

    today = datetime.now(_MADRID_TZ).date()
    boundary_date = (today + timedelta(days=3)).isoformat()

    data = await _call_impl(date_iso=boundary_date)

    assert data["next_step"] != "advance_policy_violated", (
        f"Lead-time gate must NOT fire for date at boundary (today+3), got '{data['next_step']}'"
    )


# ---------------------------------------------------------------------------
# T-LT-03: closed_day takes precedence over lead-time (gate ordering)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_day_takes_precedence_over_lead_time():
    """T-LT-03 (R2/S3): date that is BOTH a closed day AND within lead-time window.

    Step 6c (closed_day) must fire before Step 6d (lead-time).
    Result must be closed_day_required, NOT advance_policy_violated.
    """
    from datetime import datetime

    today = datetime.now(_MADRID_TZ).date()
    # Use a date within the lead-time window (today+2 < today+3) that is also "closed"
    closed_and_below_min = (today + timedelta(days=2)).isoformat()

    patches_override = {
        "shared.business_hours_validator.is_date_closed": AsyncMock(return_value=True),
    }

    data = await _call_impl(date_iso=closed_and_below_min, patches_override=patches_override)

    assert data["next_step"] == "closed_day_required", (
        f"closed_day gate must take precedence over lead-time gate, got '{data['next_step']}'"
    )


# ---------------------------------------------------------------------------
# T-LT-04: date_iso=None → lead-time gate skipped (no regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_time_gate_skipped_when_no_date():
    """T-LT-04 (R3/S4): date_iso=None → lead-time gate is not evaluated.

    With stylist resolved and no date, tool should emit offer_slots — same as before this change.
    """
    data = await _call_impl(date_iso=None)

    assert data["next_step"] == "offer_slots", (
        f"With no date, expected 'offer_slots' (gate skipped), got '{data['next_step']}'"
    )
    assert data["next_step"] != "advance_policy_violated", (
        "Lead-time gate must NOT fire when date_iso is None"
    )


@pytest.mark.asyncio
async def test_stylist_required_payload_empty_when_no_active_stylists():
    """No active stylists → payload.stylists == []."""
    ctx, _ = _make_session_ctx()

    from database.models import ServiceCategory

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["service-uuid-1"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(return_value={ServiceCategory.HAIRDRESSING}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            new=AsyncMock(return_value=[]),
        ),
    ):
        data = await _call_update_booking(
            services=["Corte Dama"],
            no_more_services=True,
            extras_asked=True,
        )

    assert data["next_step"] == "stylist_required"
    payload = data.get("payload", {})
    assert payload.get("stylists") == [], (
        f"payload.stylists should be [] when no active stylists, got {payload.get('stylists')}"
    )


@pytest.mark.asyncio
async def test_stylist_required_payload_on_unknown_stylist():
    """Unknown stylist name → rejected/stylist_required with payload.stylists populated."""
    ctx, _ = _make_session_ctx()

    active_first_names = ["Ana", "Marta"]

    from database.models import ServiceCategory

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["service-uuid-1"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(return_value={ServiceCategory.HAIRDRESSING}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            new=AsyncMock(return_value=None),  # stylist name not found
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            new=AsyncMock(return_value=active_first_names),
        ),
    ):
        data = await _call_update_booking(
            services=["Corte Dama"],
            no_more_services=True,
            extras_asked=True,
            stylist_name="Desconocida",
        )

    assert data["next_step"] == "stylist_required"
    payload = data.get("payload", {})
    assert payload.get("stylists") == active_first_names
