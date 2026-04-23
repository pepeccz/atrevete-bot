"""Unit tests for _sanitize_notes helper in agent.tools.book."""

from __future__ import annotations

import pytest

from agent.tools.book import _sanitize_notes


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("\t\n  ", None),
        ("hola\x00mundo", "holamundo"),
        ("a\rb\x1fc\x7fd\x9fe", "abcde"),
        ("a\n\nb\tc", "a b c"),
        ("  espacios   multiples  ", "espacios multiples"),
        ("cita normal", "cita normal"),
    ],
)
def test_sanitize_notes_basic_cases(raw: str | None, expected: str | None) -> None:
    assert _sanitize_notes(raw) == expected


def test_sanitize_notes_truncates_to_280_with_ellipsis() -> None:
    raw = "x" * 400
    result = _sanitize_notes(raw)
    assert result is not None
    assert len(result) == 280
    assert result.endswith("…")
    assert result[:-1] == "x" * 279


def test_sanitize_notes_exactly_280_not_truncated() -> None:
    raw = "y" * 280
    result = _sanitize_notes(raw)
    assert result == raw
    assert not result.endswith("…")


def test_sanitize_notes_281_is_truncated() -> None:
    raw = "z" * 281
    result = _sanitize_notes(raw)
    assert result is not None
    assert len(result) == 280
    assert result.endswith("…")


def test_sanitize_notes_idempotent() -> None:
    raw = "cliente alérgica al amoniaco, avisar antes de aplicar"
    once = _sanitize_notes(raw)
    twice = _sanitize_notes(once)
    assert once == twice
