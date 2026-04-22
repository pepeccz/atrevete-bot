"""Tests for escape resolver — Task 4.5."""

import pytest

from agent.booking.resolvers.escape import resolve_escape


def _state():
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected_kind",
    [
        ("cancelar", "cancel"),
        ("no quiero", "cancel"),
        ("anular", "cancel"),
        ("empezar de cero", "start_over"),
        ("borrar todo", "start_over"),
        ("reiniciar", "start_over"),
        ("cambiar fecha", "change_date"),
        ("otro día", "change_date"),
        ("otra fecha", "change_date"),
        ("mejor otra cosa", "change_service"),
        ("cambiar servicio", "change_service"),
        ("otro servicio", "change_service"),
        ("con otra", "change_stylist"),
        ("cambiar estilista", "change_stylist"),
        ("otro estilista", "change_stylist"),
    ],
)
async def test_resolve_escape_match(text, expected_kind):
    result = await resolve_escape(text, _state())
    assert result is not None
    assert result["booking"]["_escape_intent"] == expected_kind


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "quiero reservar",
        "mañana a las 10",
        "soy Ana García",
    ],
)
async def test_resolve_escape_no_match(text):
    result = await resolve_escape(text, _state())
    assert result is None
