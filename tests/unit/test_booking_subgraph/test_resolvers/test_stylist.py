"""
Phase 3 — stylist resolver tests (R1.5).

"con Laura" → last_stylist="Laura"; ANY_AVAILABLE sentinel does NOT trigger;
unknown name → not matched.
"""

from __future__ import annotations

_KNOWN_STYLISTS = ["Laura", "Ana", "María"]


def test_explicit_name_match():
    from agent.booking.resolvers.stylist import resolve

    result = resolve("quiero con Laura", {}, {"known_stylists": _KNOWN_STYLISTS})
    assert result is not None and result["matched"]
    assert result["patch"]["last_stylist"] == "Laura"


def test_any_available_sentinel_not_triggered():
    from agent.booking.resolvers.stylist import resolve

    result = resolve("cualquiera", {}, {"known_stylists": _KNOWN_STYLISTS})
    assert result is None or not result.get("matched")


def test_unknown_name_not_matched():
    from agent.booking.resolvers.stylist import resolve

    result = resolve("con Valentina", {}, {"known_stylists": _KNOWN_STYLISTS})
    assert result is None or not result.get("matched")


def test_user_action_provide_field():
    from agent.booking.resolvers.stylist import resolve

    result = resolve("con Ana", {}, {"known_stylists": _KNOWN_STYLISTS})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "PROVIDE_FIELD"


def test_guard_already_set():
    from agent.booking.resolvers.stylist import resolve

    bc = {"last_stylist": "Laura"}
    result = resolve("con Ana", bc, {"known_stylists": _KNOWN_STYLISTS})
    assert result is None or not result.get("matched")
