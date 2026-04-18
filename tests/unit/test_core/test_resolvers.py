"""Unit tests for agent.core.resolvers — registry + telemetry (R3, R4, R5, R6)."""
from __future__ import annotations

import logging

import pytest

from agent.core.resolvers import (
    _clear_for_tests,
    get,
    get_ordered,
    invoke_with_telemetry,
    register,
    registered_names,
    unregister,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure the registry is empty before and after every test."""
    _clear_for_tests()
    yield
    _clear_for_tests()


# ---------------------------------------------------------------------------
# R3 — register / get / registered_names (preserve insertion order)
# ---------------------------------------------------------------------------


def test_register_and_get_preserves_order():
    fn_a = lambda text, state: None  # noqa: E731
    fn_b = lambda text, state: None  # noqa: E731

    register("a", fn_a)
    register("b", fn_b)

    assert registered_names() == ["a", "b"]
    assert get("a") is fn_a
    assert get("b") is fn_b


# ---------------------------------------------------------------------------
# R3 — duplicate registration raises ValueError
# ---------------------------------------------------------------------------


def test_duplicate_register_raises_valueerror():
    fn = lambda text, state: None  # noqa: E731
    register("dup", fn)
    with pytest.raises(ValueError, match="already registered"):
        register("dup", fn)


# ---------------------------------------------------------------------------
# R4 — unregister
# ---------------------------------------------------------------------------


def test_unregister_removes_and_raises_keyerror():
    fn = lambda text, state: None  # noqa: E731

    register("x", fn)
    unregister("x")

    with pytest.raises(KeyError):
        get("x")


def test_unregister_nonexistent_raises_keyerror():
    with pytest.raises(KeyError):
        unregister("nonexistent")


# ---------------------------------------------------------------------------
# R5 — get_ordered: respects caller-supplied order
# ---------------------------------------------------------------------------


def test_get_ordered_respects_argument_order():
    fn_a = lambda text, state: None  # noqa: E731
    fn_b = lambda text, state: None  # noqa: E731
    fn_c = lambda text, state: None  # noqa: E731

    register("a", fn_a)
    register("b", fn_b)
    register("c", fn_c)

    result = get_ordered(["c", "a"])
    assert result == [fn_c, fn_a]


def test_get_ordered_raises_keyerror_for_unknown():
    with pytest.raises(KeyError):
        get_ordered(["missing"])


# ---------------------------------------------------------------------------
# R6 — invoke_with_telemetry emits all 7 required structured fields
# ---------------------------------------------------------------------------


def test_invoke_with_telemetry_unmatched_resolver(caplog):
    """Resolver returning None → matched=False, fuzzy_distance=-1.0, matched_phrase=''."""
    fn = lambda text, state: None  # noqa: E731
    register("noop", fn)

    with caplog.at_level(logging.INFO, logger="agent.core.resolvers"):
        invoke_with_telemetry("noop", "hola", {}, conversation_id="conv-1", turn=1)

    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.resolver == "noop"  # type: ignore[attr-defined]
    assert rec.conversation_id == "conv-1"  # type: ignore[attr-defined]
    assert rec.turn == 1  # type: ignore[attr-defined]
    assert isinstance(rec.user_text_hash, str) and len(rec.user_text_hash) == 16  # type: ignore[attr-defined]
    assert rec.matched is False  # type: ignore[attr-defined]
    assert rec.fuzzy_distance == -1.0  # type: ignore[attr-defined]
    assert rec.matched_phrase == ""  # type: ignore[attr-defined]


def test_invoke_with_telemetry_matched_resolver_with_meta(caplog):
    """Resolver returning patch with _telemetry → meta surfaced in record."""

    def fn(text, state):
        return {"result": True, "_telemetry": {"matched_phrase": "nada", "fuzzy_distance": 0.9}}

    register("matcher", fn)

    with caplog.at_level(logging.INFO, logger="agent.core.resolvers"):
        invoke_with_telemetry("matcher", "nada más", {})

    rec = caplog.records[0]
    assert rec.matched is True  # type: ignore[attr-defined]
    assert rec.matched_phrase == "nada"  # type: ignore[attr-defined]
    assert rec.fuzzy_distance == pytest.approx(0.9)  # type: ignore[attr-defined]


def test_invoke_with_telemetry_raw_user_text_never_logged(caplog):
    """Privacy: raw user_text MUST NOT appear in any record attribute or message."""
    secret = "numero secreto 42"

    fn = lambda text, state: None  # noqa: E731
    register("privacy", fn)

    with caplog.at_level(logging.INFO, logger="agent.core.resolvers"):
        invoke_with_telemetry("privacy", secret, {})

    rec = caplog.records[0]
    # Check message and all extra attributes set on the record.
    assert secret not in rec.getMessage()
    for attr_val in vars(rec).values():
        assert secret not in str(attr_val)
