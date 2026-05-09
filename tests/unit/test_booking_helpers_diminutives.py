"""T2 — Diminutive stripping helper.

Tests for _strip_diminutive and BookingQueryService.resolve_service_ids diminutive integration.
Spec R5.1 – R5.4 / ADR-10.

Post-PR#2: _resolve_service_ids moved to BookingQueryService; tests use
get_async_session mock to inject controlled DB rows.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# T2.1 — _strip_diminutive unit tests (pure logic)
# ---------------------------------------------------------------------------


def test_strip_diminutive_peinadito():
    from agent.tools.booking_helpers import _strip_diminutive

    stem = _strip_diminutive("peinadito")
    assert stem is not None
    # stem should start with "peinad"
    assert stem.startswith("peinad")


def test_strip_diminutive_cortita():
    from agent.tools.booking_helpers import _strip_diminutive

    stem = _strip_diminutive("cortita")
    assert stem is not None
    assert stem.startswith("cort")


def test_strip_diminutive_non_diminutive_unchanged():
    from agent.tools.booking_helpers import _strip_diminutive

    result = _strip_diminutive("corte")
    assert result is None  # not a diminutive


def test_strip_diminutive_cafe_rejected_short_stem():
    """'café' → stem 'ca' rejected (len < 4)."""
    from agent.tools.booking_helpers import _strip_diminutive

    # 'cafecito' → stem 'cafec' then + 'e' / '' etc — but 'café' itself has no diminutive suffix
    result = _strip_diminutive("cafe")
    assert result is None


def test_strip_diminutive_masajito_returns_stem():
    """'masajito' → strip suffix → 'masaj' → should be able to try stems."""
    from agent.tools.booking_helpers import _strip_diminutive

    stem = _strip_diminutive("masajito")
    assert stem is not None  # stem found, even if no catalog match


# ---------------------------------------------------------------------------
# T2.2 — BookingQueryService.resolve_service_ids with diminutive normalization (mocked DB)
# ---------------------------------------------------------------------------


from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


def _make_session_ctx(fetchall_rows):
    """Return an async context manager that yields a session returning the given rows."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = fetchall_rows
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _ctx():
        yield mock_session

    return _ctx


@pytest.mark.asyncio
async def test_resolve_service_ids_peinadito_matches_peinado():
    """'peinadito' must resolve to the same UUID as 'peinado'."""
    peinado_id = uuid.uuid4()

    with (
        patch(
            "agent.services.booking_query_service.get_async_session",
            side_effect=_make_session_ctx([(peinado_id, "Peinado")]),
        ),
        patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower(),
        ),
    ):
        from agent.services.booking_query_service import BookingQueryService

        resolved, unknown = await BookingQueryService.resolve_service_ids(["peinadito"])

    assert str(peinado_id) in resolved, f"Expected peinado UUID in resolved, got {resolved}"
    assert unknown == []


@pytest.mark.asyncio
async def test_resolve_service_ids_cortita_matches_corte():
    """'cortita' must resolve to the same UUID as 'Corte'."""
    corte_id = uuid.uuid4()

    with (
        patch(
            "agent.services.booking_query_service.get_async_session",
            side_effect=_make_session_ctx([(corte_id, "Corte")]),
        ),
        patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower(),
        ),
    ):
        from agent.services.booking_query_service import BookingQueryService

        resolved, unknown = await BookingQueryService.resolve_service_ids(["cortita"])

    assert str(corte_id) in resolved, f"Expected corte UUID in resolved, got {resolved}"
    assert unknown == []


@pytest.mark.asyncio
async def test_resolve_service_ids_masajito_returns_unknown():
    """'masajito' when no match → returns unknown, no exception."""
    corte_id = uuid.uuid4()

    with (
        patch(
            "agent.services.booking_query_service.get_async_session",
            # Catalog only has Corte — masajito won't match
            side_effect=_make_session_ctx([(corte_id, "Corte")]),
        ),
        patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower(),
        ),
    ):
        from agent.services.booking_query_service import BookingQueryService

        resolved, unknown = await BookingQueryService.resolve_service_ids(["masajito"])

    assert resolved == []
    assert "masajito" in unknown


@pytest.mark.asyncio
async def test_resolve_service_ids_non_diminutive_unchanged():
    """Non-diminutive input 'corte' must match exactly as before."""
    corte_id = uuid.uuid4()

    with (
        patch(
            "agent.services.booking_query_service.get_async_session",
            side_effect=_make_session_ctx([(corte_id, "Corte")]),
        ),
        patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower(),
        ),
    ):
        from agent.services.booking_query_service import BookingQueryService

        resolved, unknown = await BookingQueryService.resolve_service_ids(["corte"])

    assert str(corte_id) in resolved
    assert unknown == []
