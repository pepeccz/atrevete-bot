"""
Phase 2 — customer_prefill resolver tests.

Read-only prefill from state — no patch write on mismatch.
"""

from __future__ import annotations


def _state_with_customer(name: str = "María", cid: str = "uuid-123") -> dict:
    return {"customer_first_name": name, "customer_id": cid}


def test_prefills_suggested_name_from_state():
    from agent.booking.resolvers.customer_prefill import resolve

    state = _state_with_customer("Ana")
    result = resolve("hola", {}, state)
    assert result is not None and result["matched"]
    assert result["patch"]["_suggested_customer_name"] == "Ana"


def test_prefills_customer_id_from_state():
    from agent.booking.resolvers.customer_prefill import resolve

    state = _state_with_customer("Ana", "uuid-456")
    result = resolve("hola", {}, state)
    assert result is not None and result["matched"]
    assert result["patch"]["customer_id"] == "uuid-456"


def test_no_state_customer_returns_none():
    from agent.booking.resolvers.customer_prefill import resolve

    result = resolve("hola", {}, {})
    assert result is None or not result.get("matched")


def test_already_prefilled_returns_none():
    from agent.booking.resolvers.customer_prefill import resolve

    bc = {"_suggested_customer_name": "Ana", "customer_id": "uuid-123"}
    result = resolve("hola", bc, _state_with_customer("Ana", "uuid-123"))
    assert result is None or not result.get("matched")


def test_does_not_write_customer_name_directly():
    """Prefill only writes _suggested_customer_name, never customer_name."""
    from agent.booking.resolvers.customer_prefill import resolve

    state = _state_with_customer("Ana")
    result = resolve("hola", {}, state)
    assert result is None or "customer_name" not in (result.get("patch") or {})
