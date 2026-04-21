"""
Phase 3 — add_more resolver tests (R1.8).

Negation fires only when _last_leaf=="ask_more_services"; guard blocks other contexts.
"""

from __future__ import annotations


def _bc_last_leaf(leaf: str) -> dict:
    return {"_last_leaf": leaf}


def test_negation_fires_at_ask_more_services():
    from agent.booking.resolvers.add_more import resolve

    bc = _bc_last_leaf("ask_more_services")
    result = resolve("nada mas", bc, {})
    assert result is not None and result["matched"]
    assert result["patch"].get("add_more_asked") is True


def test_affirmation_at_ask_more_services_not_matched():
    from agent.booking.resolvers.add_more import resolve

    bc = _bc_last_leaf("ask_more_services")
    result = resolve("sí quiero más", bc, {})
    assert result is None or not result.get("matched")


def test_guard_wrong_leaf_blocks():
    from agent.booking.resolvers.add_more import resolve

    bc = _bc_last_leaf("ask_name")
    result = resolve("nada mas", bc, {})
    assert result is None or not result.get("matched")


def test_no_last_leaf_blocks():
    from agent.booking.resolvers.add_more import resolve

    result = resolve("nada mas", {}, {})
    assert result is None or not result.get("matched")


def test_user_action_negate():
    from agent.booking.resolvers.add_more import resolve

    bc = _bc_last_leaf("ask_more_services")
    result = resolve("ya esta", bc, {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "NEGATE"
