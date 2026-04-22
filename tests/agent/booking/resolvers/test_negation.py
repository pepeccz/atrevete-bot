"""Tests for negation resolver — Task 4.4."""

import pytest

from agent.booking.resolvers.negation import resolve_negation


def _state():
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "no",
        "nope",
        "nada más",
        "nada mas",
        "ya está",
        "ya esta",
        "eso es todo",
        "solo eso",
        "nah",
        "ninguno",
        "ya",
        "nada",
    ],
)
async def test_resolve_negation_match(text):
    result = await resolve_negation(text, _state())
    assert result is not None
    assert result["negation"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "quiero reservar",
        "mañana a las 10",
        "no sé cuál estilista quiero para mi cita",
        "me gustaría saber más",
    ],
)
async def test_resolve_negation_no_match(text):
    result = await resolve_negation(text, _state())
    assert result is None
