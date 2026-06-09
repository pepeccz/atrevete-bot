"""T14 — I5: Unit tests for the repeated_sentences detector in qa_turn_helper.py.

Spec: REQ-I5 / SC-I5-A, SC-I5-B, SC-I5-C

TDD: Written before T15 adds the detector to qa_turn_helper.py.

Detection rules:
- Split response on sentence-ending punctuation: '.', '!', '?'
- Strip leading/trailing whitespace from each sentence
- Flag any sentence that (a) appears >= 2 times and (b) has > 5 words
- Short sentences (<= 5 words) are NOT flagged (SC-I5-C)
"""

from __future__ import annotations


def _detect_repeated_sentences(text: str) -> list[str]:
    """Import and call the detector from qa_turn_helper.

    This shim allows us to test the detector function before it exists.
    Once T15 is applied, this import will succeed and the tests will go GREEN.
    """
    from tests.e2e.harness.qa_turn_helper import detect_repeated_sentences

    return detect_repeated_sentences(text)


def test_normal_response_no_repeats() -> None:
    """SC-I5-A: Normal response without duplicate sentences returns empty list."""
    text = (
        "Hola, ¿en qué te puedo ayudar? "
        "Tenemos disponibilidad el martes por la tarde. "
        "¿Qué servicio te interesa?"
    )
    result = _detect_repeated_sentences(text)
    assert result == [], f"Expected no repeated sentences, got: {result}"


def test_exact_duplicate_sentence_detected() -> None:
    """SC-I5-B: Exact duplicate sentence (>5 words) is flagged."""
    duplicate = "Hola, ¿cómo puedo ayudarte hoy con tu reserva?"
    text = f"{duplicate} {duplicate}"
    result = _detect_repeated_sentences(text)
    assert len(result) >= 1, f"Expected at least one repeated sentence, got: {result}"
    assert any(duplicate.strip().rstrip(".!?") in r or r in duplicate for r in result)


def test_short_repeated_fragment_not_flagged() -> None:
    """SC-I5-C: Repeated fragments of <= 5 words are NOT flagged."""
    text = "Hola. Hola. Hola. ¿En qué te puedo ayudar hoy con tu cita?"
    result = _detect_repeated_sentences(text)
    # "Hola" is only 1 word — must NOT be flagged
    for r in result:
        words = r.split()
        assert len(words) > 5, (
            f"Short fragment {r!r} was incorrectly flagged. "
            "Only sentences > 5 words should be flagged."
        )


def test_consecutive_duplicates_detected() -> None:
    """Duplicate sentence appearing twice consecutively is flagged."""
    sentence = "Tenemos disponibilidad el martes a las diez de la mañana."
    text = f"{sentence} {sentence}"
    result = _detect_repeated_sentences(text)
    assert len(result) >= 1, f"Expected repeated sentence to be detected, got: {result}"


def test_non_consecutive_duplicates_detected() -> None:
    """Duplicate sentence appearing in non-consecutive positions is also flagged."""
    sentence = "¿Qué servicio te gustaría reservar para esta semana?"
    text = f"{sentence} Te ayudo con lo que necesites. {sentence}"
    result = _detect_repeated_sentences(text)
    assert len(result) >= 1, f"Expected non-consecutive duplicate to be detected, got: {result}"


def test_empty_string_returns_empty() -> None:
    """Empty input returns empty list without error."""
    result = _detect_repeated_sentences("")
    assert result == []


def test_single_sentence_no_repeat() -> None:
    """Single sentence (no period or end) returns empty list."""
    result = _detect_repeated_sentences("Hola soy Maite y te ayudo con tu reserva")
    assert result == []
