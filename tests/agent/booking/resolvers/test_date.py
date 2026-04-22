"""Tests for date resolver — Task 4.6."""

from __future__ import annotations

import datetime

import pytest

from agent.booking.resolvers.date import resolve_date


def _state():
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "mañana",
        "pasado mañana",
        "el viernes",
        "próximo viernes",
        "el 25",
        "25/4",
    ],
)
async def test_resolve_date_returns_date(text):
    result = await resolve_date(text, _state())
    assert result is not None
    date_val = result["booking"]["date"]
    assert isinstance(date_val, str)
    # Must be a valid ISO date string
    parsed = datetime.date.fromisoformat(date_val)
    assert parsed >= datetime.date.today()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "quiero reservar",
        "con Marta",
        "señora",
    ],
)
async def test_resolve_date_no_match(text):
    result = await resolve_date(text, _state())
    assert result is None
