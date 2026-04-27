"""T-08, T-09 — update_booking: variant gate audience-independence + stylist payload.

RED phase: tests for:
- T-08: variant gate fires even when audience is already known
- T-09: stylist_required emits payload with stylists list + first_available_label
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
