"""
Phase 2 — confirmation resolver tests.

"sí/confirmo/correcto" → AFFIRM; "no/cancelo" → NEGATE;
guard fires only when _confirmation_shown.
"""

from __future__ import annotations


def _bc_shown(**extra) -> dict:
    return {"_confirmation_shown": True, **extra}


def test_affirmation_sets_confirmed_true():
    from agent.booking.resolvers.confirmation import resolve

    result = resolve("sí", _bc_shown(), {})
    assert result is not None
    assert result["matched"] is True
    assert result["patch"]["confirmed"] is True


def test_negation_sets_confirmed_false():
    from agent.booking.resolvers.confirmation import resolve

    result = resolve("no", _bc_shown(), {})
    assert result is not None
    assert result["matched"] is True
    assert result["patch"]["confirmed"] is False


def test_guard_not_shown_returns_none():
    from agent.booking.resolvers.confirmation import resolve

    result = resolve("sí", {}, {})
    assert result is None or not result.get("matched")


def test_already_confirmed_returns_none():
    from agent.booking.resolvers.confirmation import resolve

    result = resolve("sí", _bc_shown(confirmed=True), {})
    assert result is None or not result.get("matched")


def test_affirm_user_action():
    from agent.booking.resolvers.confirmation import resolve

    result = resolve("dale", _bc_shown(), {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "AFFIRM"


def test_negate_user_action():
    from agent.booking.resolvers.confirmation import resolve

    result = resolve("nada mas", _bc_shown(), {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "NEGATE"
