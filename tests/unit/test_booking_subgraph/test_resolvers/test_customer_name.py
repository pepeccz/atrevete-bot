"""
Phase 3 — customer_name resolver tests (R1.6).

Verbatim capture only when _last_leaf=="ask_name"; other contexts ignored.
"""

from __future__ import annotations


def test_captures_name_at_ask_name():
    from agent.booking.resolvers.customer_name import resolve

    bc = {"_last_leaf": "ask_name"}
    result = resolve("María", bc, {})
    assert result is not None and result["matched"]
    assert result["patch"]["customer_name"] == "María"


def test_guard_wrong_leaf_blocks():
    from agent.booking.resolvers.customer_name import resolve

    bc = {"_last_leaf": "ask_notes"}
    result = resolve("María", bc, {})
    assert result is None or not result.get("matched")


def test_no_last_leaf_blocks():
    from agent.booking.resolvers.customer_name import resolve

    result = resolve("María", {}, {})
    assert result is None or not result.get("matched")


def test_user_action_provide_field():
    from agent.booking.resolvers.customer_name import resolve

    bc = {"_last_leaf": "ask_name"}
    result = resolve("Carlos", bc, {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "PROVIDE_FIELD"
