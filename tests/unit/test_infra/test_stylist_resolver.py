"""
Unit tests for infra/resolvers/stylist.py — resolve_stylist pure function.

T3–T12 [R3–R11] — TDD RED→GREEN test file.
"""

from __future__ import annotations

import logging

import pytest

# ---------------------------------------------------------------------------
# T3 [R3] — Public API importable
# ---------------------------------------------------------------------------


def test_public_api_importable():
    from infra.resolvers.stylist import resolve_stylist

    assert callable(resolve_stylist)


# ---------------------------------------------------------------------------
# T4 [R4] — Digit match
# ---------------------------------------------------------------------------

_OFFERED_6 = ["Marta", "Pilar", "Victor", "Harolyn", "Rosa", "Sin preferencia"]
_OFFERED_3 = ["Marta", "Pilar", "Victor"]


@pytest.mark.parametrize(
    "text,offered,expected",
    [
        ("1", _OFFERED_6, {"last_stylist": "Marta"}),
        ("2", _OFFERED_6, {"last_stylist": "Pilar"}),
        ("6", _OFFERED_6, {"no_preference_stylist": True}),
        ("3 please", _OFFERED_3, {"last_stylist": "Victor"}),
    ],
)
def test_digit_match(text, offered, expected):
    from infra.resolvers.stylist import resolve_stylist

    assert resolve_stylist(text, offered) == expected


# ---------------------------------------------------------------------------
# T5 [R5] — No-preference phrase match
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "sin preferencia",
        "me da igual",
        "cualquiera",
        "no tengo preferencia",
        "la que sea",
    ],
)
def test_no_preference_match(text):
    from infra.resolvers.stylist import resolve_stylist

    assert resolve_stylist(text, _OFFERED_6) == {"no_preference_stylist": True}


# ---------------------------------------------------------------------------
# T6, T10, T11 [R6, R9, R10] — Name-in-tokens, collision safety, multi-token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_name",
    [
        ("Pilar", "Pilar"),
        ("Marta", "Marta"),
        ("con Pilar por favor", "Pilar"),
        ("me atiende Victor hoy", "Victor"),
    ],
)
def test_name_in_tokens(text, expected_name):
    from infra.resolvers.stylist import resolve_stylist

    result = resolve_stylist(text, _OFFERED_3)
    assert result == {"last_stylist": expected_name}


def test_victoria_does_not_match_victor():
    """R9 — 'Victoria' must NOT match 'Victor' (exact token equality, not fuzzy)."""
    from infra.resolvers.stylist import resolve_stylist

    assert resolve_stylist("Victoria no puede", _OFFERED_3) is None


def test_multi_token_with_stylist_name():
    """R10 — Multi-token tolerance: one token matches by exact equality."""
    from infra.resolvers.stylist import resolve_stylist

    assert resolve_stylist("con Pilar por favor", _OFFERED_3) == {"last_stylist": "Pilar"}


# ---------------------------------------------------------------------------
# T7, T8 [R7] — Priority order: digit > no_preference > name
# ---------------------------------------------------------------------------


def test_digit_priority_over_name():
    """R7 — Digit wins over name-in-tokens: '1 Pilar' → Marta (index 1)."""
    from infra.resolvers.stylist import resolve_stylist

    assert resolve_stylist("1 Pilar", _OFFERED_3) == {"last_stylist": "Marta"}


def test_no_preference_priority_over_name():
    """R7 — No-preference wins over name-in-tokens."""
    from infra.resolvers.stylist import resolve_stylist

    assert resolve_stylist("me da igual", ["Marta", "Pilar"]) == {"no_preference_stylist": True}


# ---------------------------------------------------------------------------
# T9 [R8] — Non-match returns None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "la semana que viene",
        "quiero un corte nuevo",
        "no sé todavía",
    ],
)
def test_non_match_returns_none(text):
    """R8 — Non-matching input returns None without raising."""
    from infra.resolvers.stylist import resolve_stylist

    assert resolve_stylist(text, _OFFERED_3) is None


# ---------------------------------------------------------------------------
# T12 [R11] — Telemetry schema via caplog
# ---------------------------------------------------------------------------


def test_telemetry_emitted(caplog):
    """R11 — Structured log with correct fields; raw user_text is hashed (PII-safe)."""
    from infra.resolvers._shared import hash_text
    from infra.resolvers.stylist import resolve_stylist

    # Use a text that differs from all canonical stylist names to verify hashing
    test_text = "quiero con Pilar"
    with caplog.at_level(logging.INFO, logger="infra.resolvers.stylist"):
        resolve_stylist(test_text, ["Pilar", "Marta"], conversation_id="x", turn_number=1)

    assert any("resolver.stylist.call" in r.message for r in caplog.records)
    record = next(r for r in caplog.records if "resolver.stylist.call" in r.message)
    assert "matched=True" in record.message
    assert "match_type=name" in record.message
    # PII check: raw user_text must not appear in log — only hash
    expected_hash = hash_text(test_text)
    assert f"user_text_hash={expected_hash}" in record.message
    # Raw text must not appear verbatim
    assert "quiero con Pilar" not in record.message
    # hash must be 8 hex chars pattern
    import re
    assert re.search(r"user_text_hash=[0-9a-f]{8}", record.message)
