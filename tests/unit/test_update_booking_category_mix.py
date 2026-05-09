"""T-5 — tests for update_booking category_mix gate.

Tests that the tool rejects mixed-category service requests with
next_step="category_mix_required" before any availability gate.

Post-PR#2: category mix logic resolved inside BookingQueryService.resolve_all.
Patches target BookingQueryService.resolve_all with has_category_mix=True/False.
All tests use mocks — no DB required.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _call_update_booking(**kwargs) -> dict:
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke(kwargs)
    return json.loads(raw)


def _make_resolve_all(
    service_ids=None,
    unknown=None,
    has_category_mix=False,
    hair_services=None,
    aesth_services=None,
    both_services=None,
    stylist_id=None,
    active_stylists=None,
):
    """Build a ResolveAllResult for mocking BookingQueryService.resolve_all."""
    from agent.services.booking_query_service import ResolveAllResult

    return ResolveAllResult(
        success=(not unknown),
        service_ids=service_ids or [],
        unknown_names=unknown or [],
        stylist_id=stylist_id,
        audience_variants=("none", "", []),
        categories=set(),
        id_to_category={},
        active_stylists=active_stylists or [],
        has_category_mix=has_category_mix,
        hair_services=hair_services or [],
        aesth_services=aesth_services or [],
        both_services=both_services or [],
        error_message=None,
    )


# ---------------------------------------------------------------------------
# T-5 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_category_mix_gate_fires_for_mixed_services():
    """Mixed HAIRDRESSING + AESTHETICS services → category_mix_required BEFORE audience gate."""
    resolve_all_result = _make_resolve_all(
        service_ids=["uuid-hair", "uuid-aesth"],
        has_category_mix=True,
        hair_services=["corte de mujer"],
        aesth_services=["manicura"],
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            new=AsyncMock(return_value=resolve_all_result),
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
    ):
        data = await _call_update_booking(
            services=["corte de mujer", "manicura"],
        )

    assert data["next_step"] == "category_mix_required", (
        f"Expected category_mix_required, got: {data['next_step']}"
    )
    assert data["status"] == "rejected"


@pytest.mark.asyncio
async def test_category_mix_gate_fires_even_with_audience_set():
    """Mixed services + audience already set → still category_mix_required (gate is before audience)."""
    resolve_all_result = _make_resolve_all(
        service_ids=["uuid-hair", "uuid-aesth"],
        has_category_mix=True,
        hair_services=["corte de mujer"],
        aesth_services=["manicura"],
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            new=AsyncMock(return_value=resolve_all_result),
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
    ):
        data = await _call_update_booking(
            services=["corte de mujer", "manicura"],
            audience="adult_female",  # audience set — gate must still fire
        )

    assert data["next_step"] == "category_mix_required"


@pytest.mark.asyncio
async def test_category_mix_payload_has_required_keys():
    """Mixed response payload must include hairdressing_services, aesthetics_services, categories."""
    resolve_all_result = _make_resolve_all(
        service_ids=["uuid-hair", "uuid-aesth"],
        has_category_mix=True,
        hair_services=["corte de mujer"],
        aesth_services=["manicura"],
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            new=AsyncMock(return_value=resolve_all_result),
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
    ):
        data = await _call_update_booking(
            services=["corte de mujer", "manicura"],
        )

    assert data["next_step"] == "category_mix_required"
    payload = data.get("payload", {})
    assert "hairdressing_services" in payload, f"Missing hairdressing_services key: {payload}"
    assert "aesthetics_services" in payload, f"Missing aesthetics_services key: {payload}"
    assert "categories" in payload, f"Missing categories key: {payload}"


@pytest.mark.asyncio
async def test_single_category_hairdressing_does_not_trigger_mix_gate():
    """HAIRDRESSING-only services → no category_mix_required, flow continues."""
    resolve_all_result = _make_resolve_all(
        service_ids=["uuid-hair"],
        has_category_mix=False,
        active_stylists=["Marta", "Ana"],
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            new=AsyncMock(return_value=resolve_all_result),
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
    ):
        data = await _call_update_booking(
            services=["corte de mujer"],
        )

    assert data["next_step"] != "category_mix_required", (
        f"Gate must NOT fire for single-category request, got: {data['next_step']}"
    )


@pytest.mark.asyncio
async def test_both_service_alongside_hair_does_not_trigger_mix_gate():
    """BOTH-category service + HAIRDRESSING → no rejection (BOTH is compatible with any)."""
    resolve_all_result = _make_resolve_all(
        service_ids=["uuid-hair", "uuid-both"],
        has_category_mix=False,  # HAIRDRESSING + BOTH = not a mix
        active_stylists=["Marta"],
    )

    with (
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_all",
            new=AsyncMock(return_value=resolve_all_result),
        ),
        patch(
            "agent.services.booking_query_service.BookingQueryService.resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
    ):
        data = await _call_update_booking(
            services=["corte de mujer", "tratamiento especial"],
        )

    assert data["next_step"] != "category_mix_required", (
        f"BOTH alongside HAIR must not trigger mix gate, got: {data['next_step']}"
    )
