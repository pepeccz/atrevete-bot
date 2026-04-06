"""
Tests for the module-level `_is_spanish_affirmative()` helper.

Spec: Task 5.1 — booking-ux-fixes
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "text",
    [
        "sí",
        "si",
        "ok",
        "dale",
        "vale",
        "claro",
        "perfecto",
        "confirmo",
        "de acuerdo",
        "correcto",
        "exacto",
        "acepto",
        "listo",
        "hecho",
        "va",
        "venga",
        # Case insensitivity
        "SI",
        "Dale",
        "OK",
        # Leading/trailing whitespace handled by .strip()
        "  sí  ",
        "  dale  ",
    ],
)
def test_is_affirmative_positive(text: str) -> None:
    """All canonical affirmative words must return True."""
    from agent.modes.booking_mode import _is_spanish_affirmative

    assert _is_spanish_affirmative(text) is True, f"Expected True for {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "no",
        "quizás",
        "luego",
        "confirmar reserva",
        "mas o menos",
        "tal vez",
        "",
        "  ",
        "nop",
        "sí quiero pero mañana",  # multi-word with additional content
        "ok pero cambia la hora",
        "dalé",  # different accent variant not in pattern
    ],
)
def test_is_affirmative_negative(text: str) -> None:
    """Non-affirmative or compound messages must return False."""
    from agent.modes.booking_mode import _is_spanish_affirmative

    assert _is_spanish_affirmative(text) is False, f"Expected False for {text!r}"
