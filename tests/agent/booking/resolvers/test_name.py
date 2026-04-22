"""Tests for name resolver — Task 4.7."""

import pytest

from agent.booking.resolvers.name import resolve_name


def _state():
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected",
    [
        ("me llamo Ana García", "Ana García"),
        ("soy Pedro Martínez", "Pedro Martínez"),
        ("me pongo de parte de Laura Sánchez", "Laura Sánchez"),
        ("de parte de Carlos López", "Carlos López"),
        # Three tokens → first + first surname only
        ("me llamo Pepe García López", "Pepe García"),
    ],
)
async def test_resolve_name_match(text, expected):
    result = await resolve_name(text, _state())
    assert result is not None
    assert result["booking"]["customer_full_name"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        # Only first name — resolver must return None (surname required)
        "me llamo Pepe",
        "soy Ana",
        # Unrelated text
        "quiero reservar",
        "mañana a las 10",
    ],
)
async def test_resolve_name_no_match(text):
    result = await resolve_name(text, _state())
    assert result is None
