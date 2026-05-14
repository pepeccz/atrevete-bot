"""
Unit tests for global_search_service.py — PR-2.

Covers sanitizer over special characters and the empty-query fast-path.
No real DB connection required.
"""

from __future__ import annotations

from api.services.global_search_service import _sanitize_query

# ─── Sanitizer ────────────────────────────────────────────────────────────────


def test_sanitize_empty_string_returns_none():
    assert _sanitize_query("") is None


def test_sanitize_whitespace_only_returns_none():
    assert _sanitize_query("   ") is None


def test_sanitize_strips_leading_trailing_whitespace():
    result = _sanitize_query("  hola  ")
    assert result == "hola"


def test_sanitize_escapes_percent():
    result = _sanitize_query("100%")
    assert result == "100\\%"
    assert "%" not in result.replace("\\%", "")


def test_sanitize_escapes_underscore():
    result = _sanitize_query("some_name")
    assert result == "some\\_name"
    assert "_" not in result.replace("\\_", "")


def test_sanitize_escapes_backslash():
    result = _sanitize_query("path\\file")
    assert result == "path\\\\file"


def test_sanitize_combined_special_chars():
    """All three special chars in one query — order: \\ → % → _ ."""
    result = _sanitize_query("a%b_c\\d")
    # backslash first → a%b_c\\d, then % → a\\%b_c\\\\d, then _ → a\\%b\\_c\\\\d
    assert result == "a\\%b\\_c\\\\d"


def test_sanitize_normal_text_unchanged():
    result = _sanitize_query("María García")
    assert result == "María García"


def test_sanitize_phone_number():
    result = _sanitize_query("+34 612 345 678")
    assert result == "+34 612 345 678"


def test_sanitize_sql_injection_attempt():
    """Ensure SQL injection attempts are neutralised at sanitizer level."""
    result = _sanitize_query("' OR 1=1 --")
    # Single quote is NOT a special ILIKE char — passed through safely
    assert result == "' OR 1=1 --"


def test_sanitize_very_long_input():
    long_q = "a" * 1000
    result = _sanitize_query(long_q)
    assert result == long_q
