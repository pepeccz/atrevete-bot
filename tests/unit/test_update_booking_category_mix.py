"""T-5 — RED tests for update_booking category_mix gate.

Tests that the tool rejects mixed-category service requests with
next_step="category_mix_required" before any availability gate.

All tests use mocks — no DB required.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
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
# T-5 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_category_mix_gate_fires_for_mixed_services():
    """Mixed HAIRDRESSING + AESTHETICS services → category_mix_required BEFORE audience gate."""
    from database.models import ServiceCategory

    ctx, _ = _make_session_ctx()

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["uuid-hair", "uuid-aesth"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            new=AsyncMock(return_value=(["uuid-hair", "uuid-aesth"], [], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(
                return_value={ServiceCategory.HAIRDRESSING, ServiceCategory.AESTHETICS}
            ),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(
                return_value={
                    "uuid-hair": ServiceCategory.HAIRDRESSING,
                    "uuid-aesth": ServiceCategory.AESTHETICS,
                }
            ),
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
    from database.models import ServiceCategory

    ctx, _ = _make_session_ctx()

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["uuid-hair", "uuid-aesth"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            new=AsyncMock(return_value=(["uuid-hair", "uuid-aesth"], [], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(
                return_value={ServiceCategory.HAIRDRESSING, ServiceCategory.AESTHETICS}
            ),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(
                return_value={
                    "uuid-hair": ServiceCategory.HAIRDRESSING,
                    "uuid-aesth": ServiceCategory.AESTHETICS,
                }
            ),
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
    from database.models import ServiceCategory

    ctx, _ = _make_session_ctx()

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["uuid-hair", "uuid-aesth"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            new=AsyncMock(return_value=(["uuid-hair", "uuid-aesth"], [], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(
                return_value={ServiceCategory.HAIRDRESSING, ServiceCategory.AESTHETICS}
            ),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            new=AsyncMock(
                return_value={
                    "uuid-hair": ServiceCategory.HAIRDRESSING,
                    "uuid-aesth": ServiceCategory.AESTHETICS,
                }
            ),
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
    from database.models import ServiceCategory

    ctx, session_mock = _make_session_ctx()

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["uuid-hair"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            new=AsyncMock(return_value=(["uuid-hair"], [], [], [])),
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
            "agent.tools._booking_helpers._resolve_active_stylists",
            new=AsyncMock(return_value=["Marta", "Ana"]),
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
    from database.models import ServiceCategory

    ctx, _ = _make_session_ctx()

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(["uuid-hair", "uuid-both"], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            new=AsyncMock(return_value=(["uuid-hair", "uuid-both"], [], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=("none", "", [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(
                return_value={ServiceCategory.HAIRDRESSING, ServiceCategory.BOTH}
            ),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            new=AsyncMock(return_value=["Marta"]),
        ),
    ):
        data = await _call_update_booking(
            services=["corte de mujer", "tratamiento especial"],
        )

    assert data["next_step"] != "category_mix_required", (
        f"BOTH alongside HAIR must not trigger mix gate, got: {data['next_step']}"
    )
