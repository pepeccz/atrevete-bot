"""Unit tests for new update_booking priority matrix gates.

Tests the new next_step values: extras_loop_required, name_required, notes_optional.
All tests are RED before T4 (new args + matrix reorder in update_booking.py).

Spec refs: SPEC-1.1→1.5, SPEC-2.1→2.3, SPEC-3.1→3.3, SPEC-4.1→4.2, ADR-2.
"""
from __future__ import annotations

import json
from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared mock setup helpers
# ---------------------------------------------------------------------------


def _make_session_ctx():
    """Return an async context manager mock for get_async_session()."""
    session_mock = AsyncMock()
    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=session_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)
    return ctx_mock, session_mock


async def _call_update_booking(**kwargs) -> dict:
    """Invoke update_booking.ainvoke and return parsed JSON dict."""
    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke(kwargs)
    return json.loads(raw)


async def _call_with_mocks(resolved_ids=None, unknown=None, audience_kind="none", **booking_kwargs) -> dict:
    """Call update_booking with DB helpers mocked out."""
    if resolved_ids is None:
        resolved_ids = ["service-uuid-1"]
    if unknown is None:
        unknown = []

    ctx, _ = _make_session_ctx()

    from database.models import ServiceCategory

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            new=AsyncMock(return_value=(resolved_ids, unknown)),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=(audience_kind, "", [])),
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
            new=AsyncMock(return_value="stylist-uuid-1"),
        ),
        # Patch is_date_closed so tests don't hit the DB and always assume an open day.
        # Tests that need closed-day behaviour should use test_update_booking.py.
        patch(
            "shared.business_hours_validator.is_date_closed",
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
        services=["Corte Dama"],
        no_more_services=False,
        extras_asked=False,
    )

    assert data["next_step"] == "extras_loop_required"
    assert data["collected"]["extras_asked"] is True


@pytest.mark.asyncio
async def test_extras_loop_self_clears():
    """extras_asked=True → does NOT fire extras_loop_required."""
    data = await _call_with_mocks(
        services=["Corte Dama"],
        no_more_services=False,
        extras_asked=True,
    )

    assert data["next_step"] != "extras_loop_required"


@pytest.mark.asyncio
async def test_no_more_services_skips_extras_loop():
    """no_more_services=True → extras_loop_required never fires regardless of extras_asked."""
    data = await _call_with_mocks(
        services=["Corte Dama"],
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
        services=["Corte Dama"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso="2026-05-10",
        customer_full_name=None,
        customer_known=False,
    )

    assert data["next_step"] == "name_required"


@pytest.mark.asyncio
async def test_name_required_skipped_when_customer_known():
    """customer_known=True → does NOT fire name_required; proceeds to notes_optional."""
    data = await _call_with_mocks(
        services=["Corte Dama"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso="2026-05-10",
        customer_full_name=None,
        customer_known=True,
    )

    assert data["next_step"] != "name_required"


@pytest.mark.asyncio
async def test_name_required_skipped_when_full_name_provided():
    """customer_full_name='Ana García' → name guard satisfied, proceeds."""
    data = await _call_with_mocks(
        services=["Corte Dama"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso="2026-05-10",
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
        services=["Corte Dama"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso="2026-05-10",
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
        services=["Corte Dama"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso="2026-05-10",
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
    """All guards satisfied → booking_ready."""
    data = await _call_with_mocks(
        services=["Corte Dama"],
        no_more_services=True,
        extras_asked=True,
        stylist_name="Marta",
        date_iso="2026-05-10",
        customer_full_name="Ana García",
        customer_known=False,
        notes_asked=True,
    )

    assert data["next_step"] == "booking_ready"


# ---------------------------------------------------------------------------
# T3e — priority: extras before stylist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_priority_matrix_extras_before_stylist():
    """services=[X], no stylist, extras_asked=False → extras_loop_required wins over stylist_required."""
    data = await _call_with_mocks(
        services=["Corte Dama"],
        no_more_services=False,
        extras_asked=False,
        # no stylist provided → if order is wrong, stylist_required would fire first
    )

    assert data["next_step"] == "extras_loop_required"
