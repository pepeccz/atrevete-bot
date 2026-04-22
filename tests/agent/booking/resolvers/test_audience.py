"""Tests for audience resolver — Task 4.2."""

import pytest

from agent.booking.resolvers.audience import resolve_audience


def _state():
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected",
    [
        # adult_female
        ("para una señora", "adult_female"),
        ("quiero para dama", "adult_female"),
        ("soy mujer", "adult_female"),
        ("corte femenino", "adult_female"),
        ("SEÑORAS por favor", "adult_female"),
        # adult_male
        ("para un señor", "adult_male"),
        ("es para mi caballero", "adult_male"),
        ("corte para hombre", "adult_male"),
        ("masculino por favor", "adult_male"),
        # child_female
        ("es para mi niña", "child_female"),
        ("la nena", "child_female"),
        ("mi hija", "child_female"),
        # child_male
        ("para el niño", "child_male"),
        ("mi nene", "child_male"),
        ("para mi hijo", "child_male"),
        ("para bebe", "child_male"),
        ("para bebé", "child_male"),
        # unisex
        ("unisex por favor", "unisex"),
    ],
)
async def test_resolve_audience_match(text, expected):
    result = await resolve_audience(text, _state())
    assert result is not None
    assert result["booking"]["audience"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "quiero reservar",
        "mañana a las 10",
        "con Marta",
        # ambiguous: both genders
        "para hombre o mujer",
    ],
)
async def test_resolve_audience_no_match(text):
    result = await resolve_audience(text, _state())
    assert result is None
