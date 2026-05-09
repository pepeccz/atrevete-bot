"""Unit tests for update_booking priority matrix gates.

Tests the next_step values: extras_loop_required, name_required, notes_optional.

Post-PR#2: patches target BookingQueryService.resolve_all and
BookingQueryService.resolve_audience_variants instead of _booking_helpers.* functions.

Spec refs: SPEC-1.1→1.5, SPEC-2.1→2.3, SPEC-3.1→3.3, SPEC-4.1→4.2, ADR-2.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

# Future open date (>= 3 days ahead to pass lead-time gate; assumed open Monday)
_FUTURE_DATE = (date.today() + timedelta(days=10)).isoformat()


# ---------------------------------------------------------------------------
# Shared mock setup helpers
# ---------------------------------------------------------------------------


async def _call_update_booking(**kwargs) -> dict:
    """Invoke update_booking.ainvoke and return parsed JSON dict."""
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke(kwargs)
    return json.loads(raw)


def _make_resolve_all(
    service_ids=None,
    unknown=None,
    stylist_id="stylist-uuid-1",
    active_stylists=None,
):
    """Build a ResolveAllResult mock for BookingQueryService.resolve_all."""
    from agent.services.booking_query_service import ResolveAllResult

    return ResolveAllResult(
        success=(not unknown),
        service_ids=service_ids or ["service-uuid-1"],
        unknown_names=unknown or [],
        stylist_id=stylist_id,
        audience_variants=("none", "", []),
        categories=set(),
        id_to_category={},
        active_stylists=active_stylists or [],
        has_category_mix=False,
        hair_services=[],
        aesth_services=[],
        both_services=[],
        error_message=None,
    )


async def _call_with_mocks(
    resolved_ids=None,
    unknown=None,
    audience_kind="none",
    **booking_kwargs,
) -> dict:
    """Call update_booking with DB helpers mocked out via BookingQueryService."""
    if resolved_ids is None:
        resolved_ids = ["service-uuid-1"]
    if unknown is None:
        unknown = []

    resolve_all_result = _make_resolve_all(service_ids=resolved_ids, unknown=unknown)

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            new=AsyncMock(return_value=resolve_all_result),
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            new=AsyncMock(return_value=(audience_kind, "", [])),
        ),
        # Patch is_date_closed so tests don't hit the DB and always assume an open day.
        patch(
            "agent.tools._booking_validators.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
    ):
        return await _call_update_booking(**booking_kwargs)


# ---------------------------------------------------------------------------
# T3a — extras_loop_required gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extras_loop_required_fires_once():
    """services=[X], no_more_services=False, extras_asked=False → extras_loop_required + extras_asked=True."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=False,
        extras_asked=False,
    )

    assert data["next_step"] == "extras_loop_required"
    assert data["collected"]["extras_asked"] is True


@pytest.mark.asyncio
async def test_extras_loop_self_clears():
    """extras_asked=True → does NOT fire extras_loop_required."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=False,
        extras_asked=True,
    )

    assert data["next_step"] != "extras_loop_required"


@pytest.mark.asyncio
async def test_no_more_services_skips_extras_loop():
    """no_more_services=True → extras_loop_required never fires regardless of extras_asked."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=True,
        extras_asked=False,
    )

    assert data["next_step"] != "extras_loop_required"


# ---------------------------------------------------------------------------
# T3b — name_required gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_name_required_fires_when_customer_unknown():
    """All slots resolved, customer_full_name=None, customer_known=False → name_required."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso=_FUTURE_DATE,
        customer_full_name=None,
        customer_known=False,
    )

    assert data["next_step"] == "name_required"


@pytest.mark.asyncio
async def test_name_required_skipped_when_customer_known():
    """customer_known=True → does NOT fire name_required; proceeds to notes_optional."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso=_FUTURE_DATE,
        customer_full_name=None,
        customer_known=True,
    )

    assert data["next_step"] != "name_required"


@pytest.mark.asyncio
async def test_name_required_skipped_when_full_name_provided():
    """customer_full_name='Ana García' → name guard satisfied, proceeds."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso=_FUTURE_DATE,
        customer_full_name="Ana García",
        customer_known=False,
    )

    assert data["next_step"] != "name_required"


# ---------------------------------------------------------------------------
# T3c — notes_optional gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notes_optional_fires_once():
    """All earlier gates closed, notes_asked=False → notes_optional + notes_asked=True."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso=_FUTURE_DATE,
        customer_full_name="Ana García",
        customer_known=False,
        notes_asked=False,
    )

    assert data["next_step"] == "notes_optional"
    assert data["collected"]["notes_asked"] is True


@pytest.mark.asyncio
async def test_notes_optional_self_clears():
    """notes_asked=True → does NOT fire notes_optional."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso=_FUTURE_DATE,
        customer_full_name="Ana García",
        customer_known=False,
        notes_asked=True,
    )

    assert data["next_step"] != "notes_optional"


# ---------------------------------------------------------------------------
# T3d — booking_ready gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_booking_ready_only_when_all_gates_pass():
    """All guards satisfied → booking_ready.

    Requires slot_iso + matching check_availability ToolMessage to pass the pre-book gate.
    """
    import json
    from unittest.mock import MagicMock

    slot_iso = f"{_FUTURE_DATE}T10:00:00+02:00"

    # Build a matching check_availability ToolMessage
    avail_msg = MagicMock()
    avail_msg.name = "check_availability"
    avail_msg.content = json.dumps({
        "status": "ok",
        "payload": {
            "slots": [{"start_iso": slot_iso, "stylist_id": "stylist-uuid-1"}],
            "exact_match": True,
        },
    })

    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso=_FUTURE_DATE,
        customer_full_name="Ana García",
        customer_known=False,
        notes_asked=True,
        slot_iso=slot_iso,
        state={"messages": [avail_msg]},
    )

    assert data["next_step"] == "booking_ready"


# ---------------------------------------------------------------------------
# T3e — priority: extras before stylist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_priority_matrix_extras_before_stylist():
    """services=[X], no stylist, extras_asked=False → extras_loop_required wins over stylist_required."""
    data = await _call_with_mocks(
        services=["Corte de Mujer"],
        no_more_services=False,
        extras_asked=False,
        # no stylist provided → if order is wrong, stylist_required would fire first
    )

    assert data["next_step"] == "extras_loop_required"
