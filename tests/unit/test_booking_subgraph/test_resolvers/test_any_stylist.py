"""
Phase 2 — any_stylist resolver tests.

ANY_AVAILABLE sentinel → no_preference_stylist=True; explicit name does NOT trigger.
"""

from __future__ import annotations


def test_cualquiera_sets_any_available():
    from agent.booking.resolvers.any_stylist import resolve

    result = resolve("cualquiera", {}, {})
    assert result is not None and result["matched"]
    assert result["patch"]["no_preference_stylist"] is True


def test_la_primera_disponible_matches():
    from agent.booking.resolvers.any_stylist import resolve

    result = resolve("la primera con disponibilidad", {}, {})
    assert result is not None and result["matched"]
    assert result["patch"]["no_preference_stylist"] is True


def test_explicit_name_not_triggered():
    from agent.booking.resolvers.any_stylist import resolve

    result = resolve("con Laura", {}, {})
    assert result is None or not result.get("matched")


def test_guard_last_stylist_already_set():
    from agent.booking.resolvers.any_stylist import resolve

    result = resolve("cualquiera", {"last_stylist": "Ana"}, {})
    assert result is None or not result.get("matched")


def test_user_action_provide_field():
    from agent.booking.resolvers.any_stylist import resolve

    result = resolve("me da igual", {}, {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "PROVIDE_FIELD"
