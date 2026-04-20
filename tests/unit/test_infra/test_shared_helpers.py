"""
Unit tests for infra/resolvers/_shared.py — normalize_text and hash_text.

T1 [R1] — NEW test file.
"""

from __future__ import annotations

from infra.resolvers._shared import hash_text, normalize_text


class TestNormalizeText:
    def test_normalize_text_accent_strip(self):
        assert normalize_text("Señora") == "senora"

    def test_normalize_text_case(self):
        assert normalize_text("PILAR") == "pilar"

    def test_normalize_text_punctuation(self):
        assert normalize_text("dale!") == "dale"

    def test_normalize_text_whitespace(self):
        assert normalize_text("  con  Pilar  ") == "con pilar"

    def test_normalize_text_leading_punctuation(self):
        assert normalize_text("¡hola!") == "hola"

    def test_normalize_text_combined(self):
        assert normalize_text("  Señora Pilar!  ") == "senora pilar"


class TestHashText:
    def test_hash_text_length(self):
        assert len(hash_text("test")) == 8

    def test_hash_text_deterministic(self):
        assert hash_text("hello") == hash_text("hello")

    def test_hash_text_different_inputs(self):
        assert hash_text("Pilar") != hash_text("Marta")

    def test_hash_text_hex_chars(self):
        result = hash_text("test")
        assert all(c in "0123456789abcdef" for c in result)
