"""Tests for digit resolver — Task 4.3."""

import pytest

from agent.booking.resolvers.digit import resolve_digit

_SLOT_A = {"start": "2026-04-25T10:00", "stylist_name": "Marta"}
_SLOT_B = {"start": "2026-04-25T11:00", "stylist_name": "Pilar"}
_SLOT_C = {"start": "2026-04-25T12:00", "stylist_name": "Victor"}


def _state(slots=None):
    return {"booking": {"offered_slots": slots}} if slots else {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,slots,expected_index",
    [
        ("la 1", [_SLOT_A, _SLOT_B], 0),
        ("la primera", [_SLOT_A, _SLOT_B], 0),
        ("el primero", [_SLOT_A, _SLOT_B], 0),
        ("uno", [_SLOT_A, _SLOT_B], 0),
        ("primera", [_SLOT_A, _SLOT_B], 0),
        ("la 2", [_SLOT_A, _SLOT_B], 1),
        ("el segundo", [_SLOT_A, _SLOT_B], 1),
        ("dos", [_SLOT_A, _SLOT_B], 1),
        ("segunda", [_SLOT_A, _SLOT_B], 1),
        ("la 3", [_SLOT_A, _SLOT_B, _SLOT_C], 2),
        ("el tercero", [_SLOT_A, _SLOT_B, _SLOT_C], 2),
        # "esa" / "esta" → last offered (or index 0 when only 1 slot)
        ("esa", [_SLOT_A], 0),
        ("esta misma", [_SLOT_A, _SLOT_B], 1),
        ("esta", [_SLOT_A, _SLOT_B], 1),
    ],
)
async def test_resolve_digit_match(text, slots, expected_index):
    result = await resolve_digit(text, _state(slots))
    assert result is not None
    assert result["booking"]["selected_slot"] == slots[expected_index]


@pytest.mark.asyncio
async def test_resolve_digit_no_slots_in_state():
    """No offered_slots in state → None regardless of text."""
    result = await resolve_digit("la 1", _state())
    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["quiero reservar", "mañana", "con Marta"])
async def test_resolve_digit_non_digit_text(text):
    result = await resolve_digit(text, _state([_SLOT_A, _SLOT_B]))
    assert result is None


@pytest.mark.asyncio
async def test_resolve_digit_index_out_of_range():
    """Referring to slot 3 when only 2 available → None."""
    result = await resolve_digit("la 3", _state([_SLOT_A, _SLOT_B]))
    assert result is None
