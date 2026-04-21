"""
Phase 3 — notes resolver tests (R1.7).

negation → notes_state=skipped; text → notes_state=provided+notes=<text>;
guard only when _last_leaf=="ask_notes".
"""

from __future__ import annotations


def _bc_ask_notes() -> dict:
    return {"_last_leaf": "ask_notes"}


def test_negation_sets_skipped():
    from agent.booking.resolvers.notes import resolve

    result = resolve("sin notas", _bc_ask_notes(), {})
    assert result is not None and result["matched"]
    assert result["patch"]["notes_state"] == "skipped"


def test_text_sets_provided():
    from agent.booking.resolvers.notes import resolve

    result = resolve("soy alérgica al tinte", _bc_ask_notes(), {})
    assert result is not None and result["matched"]
    assert result["patch"]["notes_state"] == "provided"
    assert result["patch"]["notes"] == "soy alérgica al tinte"


def test_guard_wrong_leaf_blocks():
    from agent.booking.resolvers.notes import resolve

    bc = {"_last_leaf": "ask_name"}
    result = resolve("sin notas", bc, {})
    assert result is None or not result.get("matched")


def test_no_leaf_blocks():
    from agent.booking.resolvers.notes import resolve

    result = resolve("sin notas", {}, {})
    assert result is None or not result.get("matched")


def test_user_action_negate_on_skip():
    from agent.booking.resolvers.notes import resolve

    result = resolve("nada mas", _bc_ask_notes(), {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "NEGATE"


def test_user_action_provide_field_on_text():
    from agent.booking.resolvers.notes import resolve

    result = resolve("tengo alergia al amoniaco", _bc_ask_notes(), {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "PROVIDE_FIELD"
