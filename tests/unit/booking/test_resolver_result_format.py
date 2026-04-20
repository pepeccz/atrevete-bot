"""
RED tests for B.3.2 — resolver wrapper result format.

Parametrised over every resolver wrapper in agent/booking/patch_pipeline.py.
For each, asserts the return value is None or a dict with at least
source, matched, patch keys.

Must FAIL on master because resolve_confirmation, resolve_stylist_selection,
resolve_digit_selection, resolve_customer_from_state, resolve_service_category
do not exist yet (only resolve_add_more_negation from B.2).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _minimal_bc(**overrides: Any) -> dict:
    """Return a minimal booking context."""
    base: dict[str, Any] = {
        "last_services": [],
        "add_more_asked": False,
        "_confirmation_shown": False,
        "confirmed": None,
    }
    base.update(overrides)
    return base


def _minimal_state(**overrides: Any) -> dict:
    """Return a minimal ConversationState dict."""
    base: dict[str, Any] = {
        "conversation_id": "test-conv-001",
        "total_message_count": 1,
        "booking_context": _minimal_bc(),
    }
    base.update(overrides)
    return base


def _assert_resolver_result(result: Any, resolver_name: str) -> None:
    """Assert that result is None or a valid ResolverResult dict."""
    if result is None:
        return  # None is always valid (no match)
    assert isinstance(
        result, dict
    ), f"{resolver_name} returned {type(result).__name__!r}, expected dict or None"
    required_keys = {"source", "matched", "patch"}
    missing = required_keys - result.keys()
    assert (
        not missing
    ), f"{resolver_name} result missing required keys: {missing}. Got: {list(result.keys())}"
    assert isinstance(
        result["patch"], dict
    ), f"{resolver_name} result['patch'] must be a dict, got {type(result['patch'])!r}"


# ---------------------------------------------------------------------------
# Test: resolve_add_more_negation (exists from B.2)
# ---------------------------------------------------------------------------


def test_resolve_add_more_negation_returns_valid_result_or_none() -> None:
    """resolve_add_more_negation returns None or a valid ResolverResult."""
    from agent.booking.patch_pipeline import resolve_add_more_negation  # noqa: PLC0415

    bc = _minimal_bc(add_more_asked=False)
    state = _minimal_state(booking_context=bc)
    result = resolve_add_more_negation("nada más", state, bc)
    _assert_resolver_result(result, "resolve_add_more_negation")


# ---------------------------------------------------------------------------
# Test: resolve_confirmation (B.3.5 — not yet created)
# ---------------------------------------------------------------------------


def test_resolve_confirmation_returns_valid_result_or_none() -> None:
    """resolve_confirmation returns None or a valid ResolverResult."""
    from agent.booking.patch_pipeline import resolve_confirmation  # noqa: PLC0415

    bc = _minimal_bc(_confirmation_shown=True, confirmed=None)
    result = resolve_confirmation("sí, confirmo", bc)
    _assert_resolver_result(result, "resolve_confirmation")


def test_resolve_confirmation_no_fire_without_confirmation_shown() -> None:
    """resolve_confirmation returns None when _confirmation_shown is False."""
    from agent.booking.patch_pipeline import resolve_confirmation  # noqa: PLC0415

    bc = _minimal_bc(_confirmation_shown=False, confirmed=None)
    result = resolve_confirmation("dale", bc)
    assert result is None, "Should not fire when _confirmation_shown=False"


# ---------------------------------------------------------------------------
# Test: resolve_stylist_selection (B.3.5 — not yet created)
# ---------------------------------------------------------------------------


def test_resolve_stylist_selection_returns_valid_result_or_none() -> None:
    """resolve_stylist_selection returns None or a valid ResolverResult."""
    from agent.booking.patch_pipeline import resolve_stylist_selection  # noqa: PLC0415

    bc = _minimal_bc(last_services=["Corte largo"])
    offered = ["Ana", "María", "Sin preferencia"]
    result = resolve_stylist_selection("Ana", offered, bc, conversation_id="test-001", turn=2)
    _assert_resolver_result(result, "resolve_stylist_selection")


# ---------------------------------------------------------------------------
# Test: resolve_digit_selection (B.3.5 — not yet created)
# ---------------------------------------------------------------------------


def test_resolve_digit_selection_returns_valid_result_or_none() -> None:
    """resolve_digit_selection returns None or a valid ResolverResult."""
    from agent.booking.patch_pipeline import resolve_digit_selection  # noqa: PLC0415

    offered_slots = [
        {"stylist_name": "Ana", "start_time": "2026-04-22T10:00:00"},
        {"stylist_name": "María", "start_time": "2026-04-22T11:00:00"},
    ]
    bc = _minimal_bc(offered_slots=offered_slots)
    result = resolve_digit_selection("1", bc)
    _assert_resolver_result(result, "resolve_digit_selection")


def test_resolve_digit_selection_returns_none_for_non_digit() -> None:
    """resolve_digit_selection returns None for non-digit input."""
    from agent.booking.patch_pipeline import resolve_digit_selection  # noqa: PLC0415

    offered_slots = [{"stylist_name": "Ana", "start_time": "2026-04-22T10:00:00"}]
    bc = _minimal_bc(offered_slots=offered_slots)
    result = resolve_digit_selection("quiero el de Ana", bc)
    assert result is None, "Should return None for non-digit input"


# ---------------------------------------------------------------------------
# Test: resolve_customer_from_state (B.3.5 — not yet created)
# ---------------------------------------------------------------------------


def test_resolve_customer_from_state_returns_valid_result_or_none() -> None:
    """resolve_customer_from_state returns None or a valid ResolverResult."""
    from agent.booking.patch_pipeline import resolve_customer_from_state  # noqa: PLC0415

    state = _minimal_state(customer_first_name="María", customer_id="cust-001")
    bc = _minimal_bc()  # No customer info yet
    result = resolve_customer_from_state(state, bc)
    _assert_resolver_result(result, "resolve_customer_from_state")


def test_resolve_customer_from_state_returns_none_when_already_set() -> None:
    """resolve_customer_from_state returns None when name already in bc."""
    from agent.booking.patch_pipeline import resolve_customer_from_state  # noqa: PLC0415

    state = _minimal_state(customer_first_name="María")
    bc = _minimal_bc(customer_name="María García", _suggested_customer_name="María García")
    result = resolve_customer_from_state(state, bc)
    assert result is None, "Should not overwrite existing customer info"


# ---------------------------------------------------------------------------
# Test: resolve_service_category (B.3.5 — not yet created)
# ---------------------------------------------------------------------------


def test_resolve_service_category_returns_valid_result_or_none() -> None:
    """resolve_service_category returns None or a valid ResolverResult."""
    from agent.booking.patch_pipeline import resolve_service_category  # noqa: PLC0415

    # With no services → should return None
    bc = _minimal_bc()
    result = resolve_service_category(bc)
    assert result is None, "Should return None when no services"


def test_resolve_service_category_returns_none_when_already_set() -> None:
    """resolve_service_category returns None when category already cached."""
    from agent.booking.patch_pipeline import resolve_service_category  # noqa: PLC0415

    bc = _minimal_bc(last_services=["Corte largo"], last_service_category="HAIRDRESSING")
    result = resolve_service_category(bc)
    assert result is None, "Should return None when category already cached"
