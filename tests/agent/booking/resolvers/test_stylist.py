"""Tests for stylist resolver — Task 4.8."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

MARTA_ID = uuid4()
PILAR_ID = uuid4()

_STYLISTS = [
    {"id": MARTA_ID, "name": "Marta"},
    {"id": PILAR_ID, "name": "Pilar"},
    {"id": uuid4(), "name": "Victor"},
    {"id": uuid4(), "name": "Harolyn"},
    {"id": uuid4(), "name": "Rosa"},
]


def _patch_stylists():
    return patch(
        "agent.booking.resolvers.stylist._load_active_stylists",
        new=AsyncMock(return_value=_STYLISTS),
    )


def _state():
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "con Marta",
        "prefiero a Marta",
        "que sea Marta",
        "Marta",
    ],
)
async def test_resolve_stylist_exact_match(text):
    with _patch_stylists():
        from agent.booking.resolvers import stylist as _mod

        result = await _mod.resolve_stylist(text, _state())
    assert result is not None
    assert result["booking"]["stylist_id"] == MARTA_ID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "con Pilar",
        "prefiero a Pilar",
    ],
)
async def test_resolve_stylist_pilar(text):
    with _patch_stylists():
        from agent.booking.resolvers import stylist as _mod

        result = await _mod.resolve_stylist(text, _state())
    assert result is not None
    assert result["booking"]["stylist_id"] == PILAR_ID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "no preferencia",
        "cualquiera",
        "me da igual",
        "sin preferencia",
    ],
)
async def test_resolve_stylist_no_preference(text):
    with _patch_stylists():
        from agent.booking.resolvers import stylist as _mod

        result = await _mod.resolve_stylist(text, _state())
    assert result is not None
    assert result["booking"]["stylist_id"] is None
    assert result["booking"]["no_preference"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "quiero reservar",
        "mañana a las 10",
        "para señora",
    ],
)
async def test_resolve_stylist_no_match(text):
    with _patch_stylists():
        from agent.booking.resolvers import stylist as _mod

        result = await _mod.resolve_stylist(text, _state())
    assert result is None


@pytest.mark.asyncio
async def test_resolve_stylist_case_insensitive():
    with _patch_stylists():
        from agent.booking.resolvers import stylist as _mod

        result = await _mod.resolve_stylist("con MARTA", _state())
    assert result is not None
    assert result["booking"]["stylist_id"] == MARTA_ID
