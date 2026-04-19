"""
Unit tests for the booking negation resolver.

Tests normalize_for_negation() and is_negation() from infra.resolvers.negation.

TDD cycle:
- C1.1: normalize_for_negation tests (must FAIL before C1.3 — module doesn't exist)
- C1.2: is_negation tests (must FAIL before C1.3 — module doesn't exist)
"""

import time

import pytest

from infra.resolvers.negation import is_negation, normalize_for_negation


# ============================================================================
# C1.1 — normalize_for_negation tests
# ============================================================================

# 20+ canonical samples: covers typos, accents, diacritics, emoji, punct, case
CANONICAL_SAMPLES = [
    "nada más",
    "Nada Máß",
    "nomás",
    "nomas",
    "no mas",
    "nada",
    "NADA!",
    "nel",
    "nope",
    "nah 🙏",
    "ya está",
    "ya estamos",
    "listo",
    "ya",
    "basta",
    "es todo",
    "eso es todo",
    "noma",
    "ya estamos así",
    "Nada Mas.",
]

# Samples that should NOT match negation
NEGATIVE_SAMPLES = [
    "no sé cuál estilista",
    "no ahora mismo tal vez más tarde",
    "no quiero X",
    "sí",
    "vale",
    "no, quiero otro estilista",
    "no todavía",
    "me da igual",
    "espera un momento",
    "no sé qué decirte",
    "ahora no pero luego sí",
]


@pytest.mark.parametrize("text", CANONICAL_SAMPLES)
def test_normalize_returns_lowercase(text: str) -> None:
    """normalize_for_negation must return all-lowercase output."""
    result = normalize_for_negation(text)
    assert result == result.lower(), f"normalize_for_negation({text!r}) returned non-lowercase: {result!r}"


@pytest.mark.parametrize("text", CANONICAL_SAMPLES)
def test_normalize_strips_diacritics(text: str) -> None:
    """normalize_for_negation must strip diacritics (NFKD + combining strip)."""
    result = normalize_for_negation(text)
    # After normalization: no combining characters, no accented vowels
    import unicodedata
    for ch in result:
        assert not unicodedata.combining(ch), (
            f"normalize_for_negation({text!r}) left combining char {ch!r} in {result!r}"
        )


@pytest.mark.parametrize("text", CANONICAL_SAMPLES)
def test_normalize_strips_trailing_punct(text: str) -> None:
    """normalize_for_negation must strip trailing ASCII punctuation."""
    result = normalize_for_negation(text)
    trailing_punct = ".,!?¡¿…"
    assert not result or result[-1] not in trailing_punct, (
        f"normalize_for_negation({text!r}) left trailing punct in {result!r}"
    )


@pytest.mark.parametrize("text", CANONICAL_SAMPLES)
def test_normalize_no_extra_whitespace(text: str) -> None:
    """normalize_for_negation must collapse whitespace (no leading/trailing/double spaces)."""
    result = normalize_for_negation(text)
    assert result == " ".join(result.split()), (
        f"normalize_for_negation({text!r}) has extra whitespace: {result!r}"
    )


# ============================================================================
# C1.2 — is_negation tests
# ============================================================================


@pytest.mark.parametrize("text", [
    "nada más",
    "Nada Máß",
    "nomas",
    "nel",
    "nope",
    "ya está",
    "ya estamos",
    "listo",
    "ya",
    "basta",
    "es todo",
    "eso es todo",
    "nada",
    "NADA!",
    "nah 🙏",
    "no mas",
    "nomás",
    "noma",
    "ya estamos así",
    "Nada Mas.",
])
def test_is_negation_canonical_samples_match(text: str) -> None:
    """All canonical samples must return matched=True."""
    matched, _phrase, _distance = is_negation(text)
    assert matched is True, f"is_negation({text!r}) should return True, got False"


@pytest.mark.parametrize("text", [
    "no sé cuál estilista",
    "no ahora mismo tal vez más tarde",
    "no quiero X",
    "sí",
    "vale",
])
def test_is_negation_negative_samples_do_not_match(text: str) -> None:
    """Non-negation messages must return matched=False."""
    matched, _phrase, _distance = is_negation(text)
    assert matched is False, f"is_negation({text!r}) should return False, got True"


def test_is_negation_exact_match_returns_minus_one_distance() -> None:
    """Exact match must return (True, canonical, -1)."""
    matched, phrase, distance = is_negation("nada más")
    assert matched is True
    assert phrase == "nada mas"
    assert distance == -1, f"Exact match should return distance=-1, got {distance}"


def test_is_negation_fuzzy_match_returns_positive_distance() -> None:
    """Fuzzy match (typo variant) must return (True, canonical, d > 0)."""
    matched, phrase, distance = is_negation("Nada máß")
    assert matched is True
    assert phrase == "nada mas"
    assert distance > 0, f"Fuzzy match should return distance>0, got {distance}"


def test_is_negation_no_match_returns_false_none_minus_one() -> None:
    """No-match must return (False, None, -1)."""
    matched, phrase, distance = is_negation("no sé cuál estilista")
    assert matched is False
    assert phrase is None
    assert distance == -1


def test_is_negation_return_type_is_tuple_of_three() -> None:
    """is_negation must return a 3-tuple (bool, str|None, int)."""
    result = is_negation("nada más")
    assert isinstance(result, tuple)
    assert len(result) == 3
    matched, phrase, distance = result
    assert isinstance(matched, bool)
    assert phrase is None or isinstance(phrase, str)
    assert isinstance(distance, int)


def test_is_negation_performance_under_10ms() -> None:
    """is_negation must complete in under 10ms per call (R2 non-functional)."""
    start = time.perf_counter()
    is_negation("nada más")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 10, f"is_negation took {elapsed_ms:.2f}ms — must be < 10ms"


# ============================================================================
# C1.3 — Compound phrase matching (T7 canary bug fix — conv 99001)
# ============================================================================
# Root cause: is_negation("Nope nada mas") returned False because compound
# phrases (concatenation of canonicals) weren't handled. Exact lookup fails
# (not in frozenset) and fuzzy cutoff 0.86 is too strict for multi-token
# compounds. Fix: composition-of-canonicals matcher.


@pytest.mark.parametrize("text", [
    "Nope nada mas",       # the actual canary bug phrase
    "nope nada mas",
    "nah nada mas",
    "nope nomas",
    "ya listo",
    "nada mas listo",
    "ya esta listo",
    "nada ya",
    "listo ya",
])
def test_is_negation_compound_phrases_match(text: str) -> None:
    """Compounds of 2+ canonicals must match (fix for conv 99001 T7 canary)."""
    matched, _phrase, _distance = is_negation(text)
    assert matched is True, f"is_negation({text!r}) should match as compound"


@pytest.mark.parametrize("text", [
    "no quiero nada",         # contains "nada" but preceded by non-canonical
    "quiero nada mas",        # contains "nada mas" but preceded by non-canonical
    "ya casi listo",          # contains "ya" + "listo" but "casi" is filler
    "nope pero tal vez si",   # starts with canonical but continues with non-canonical
])
def test_is_negation_partial_contains_canonical_does_not_match(text: str) -> None:
    """Messages where canonicals appear mixed with non-canonical tokens must NOT match."""
    matched, _phrase, _distance = is_negation(text)
    assert matched is False, f"is_negation({text!r}) should NOT match (non-canonical filler present)"
