"""Unit tests for _booking_helpers shared utilities.

Covers _validate_full_name (SPEC-6.1 → 6.4).
RED phase: all tests should FAIL before _validate_full_name is implemented.
"""
from __future__ import annotations

from agent.tools._booking_helpers import _validate_full_name


def test_validate_full_name_returns_tuple_for_two_tokens():
    """'Ana García' → ('Ana', 'García')"""
    result = _validate_full_name("Ana García")
    assert result == ("Ana", "García")


def test_validate_full_name_returns_none_for_single_token():
    """'Maite' → None (no surname)"""
    result = _validate_full_name("Maite")
    assert result is None


def test_validate_full_name_returns_none_for_none():
    """None → None"""
    result = _validate_full_name(None)
    assert result is None


def test_validate_full_name_returns_none_for_empty_string():
    """'' → None"""
    result = _validate_full_name("")
    assert result is None


def test_validate_full_name_strips_whitespace():
    """'  Ana  García  ' → ('Ana', 'García')"""
    result = _validate_full_name("  Ana  García  ")
    assert result == ("Ana", "García")


def test_validate_full_name_three_plus_tokens():
    """'María José García' → ('María', 'José García')
    first token = first_name, rest joined = last_name (matches _split_full_name semantics).
    """
    result = _validate_full_name("María José García")
    assert result == ("María", "José García")
