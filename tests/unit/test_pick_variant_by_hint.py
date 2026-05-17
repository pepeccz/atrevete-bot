"""
Unit tests for _pick_variant_by_hint in shared/audience_maps.py.

TDD cycle: C6.3 — variant lookup helper.
Covers R3, S6.
"""

from __future__ import annotations


class TestPickVariantByHint:
    """C6.3: _pick_variant_by_hint reverse-maps hint → variant name."""

    def test_adult_female_hint_returns_senora_variant(self):
        """S6: ['Corte Señora','Corte de Hombre'] + 'adult_female' → 'Corte Señora'."""
        from shared.audience_maps import _pick_variant_by_hint

        result = _pick_variant_by_hint(
            variants=["Corte Señora", "Corte de Hombre"],
            hint="adult_female",
        )
        assert result == "Corte Señora", (
            f"Expected 'Corte Señora' for hint 'adult_female', got {result!r}"
        )

    def test_adult_male_hint_returns_caballero_variant(self):
        """S6: ['Corte Señora','Corte de Hombre'] + 'adult_male' → 'Corte de Hombre'."""
        from shared.audience_maps import _pick_variant_by_hint

        result = _pick_variant_by_hint(
            variants=["Corte Señora", "Corte de Hombre"],
            hint="adult_male",
        )
        assert result == "Corte de Hombre", (
            f"Expected 'Corte de Hombre' for hint 'adult_male', got {result!r}"
        )

    def test_child_male_hint_matches_nino_variant(self):
        """S6: ['Corte de Niño', 'Corte de Niña'] + 'child_male' → 'Corte de Niño'."""
        from shared.audience_maps import _pick_variant_by_hint

        result = _pick_variant_by_hint(
            variants=["Corte de Niño", "Corte de Niña"],
            hint="child_male",
        )
        assert result == "Corte de Niño", (
            f"Expected 'Corte de Niño' for hint 'child_male', got {result!r}"
        )

    def test_baby_hint_matches_bebe_variant(self):
        """S6: ['Corte de Bebé', 'Corte Señora'] + 'baby' → 'Corte de Bebé'."""
        from shared.audience_maps import _pick_variant_by_hint

        result = _pick_variant_by_hint(
            variants=["Corte de Bebé", "Corte Señora"],
            hint="baby",
        )
        assert result == "Corte de Bebé", (
            f"Expected 'Corte de Bebé' for hint 'baby', got {result!r}"
        )

    def test_unmapped_hint_returns_none(self):
        """S6: Unmapped hint → None (graceful fallback)."""
        from shared.audience_maps import _pick_variant_by_hint

        result = _pick_variant_by_hint(
            variants=["Corte Señora", "Corte de Hombre"],
            hint="unknown_audience",
        )
        assert result is None, (
            f"Expected None for unmapped hint 'unknown_audience', got {result!r}"
        )

    def test_empty_variants_returns_none(self):
        """S6: Empty variants list → None (no match possible)."""
        from shared.audience_maps import _pick_variant_by_hint

        result = _pick_variant_by_hint(variants=[], hint="adult_female")
        assert result is None

    def test_no_matching_variant_returns_none(self):
        """S6: Variants exist but none match the hint → None."""
        from shared.audience_maps import _pick_variant_by_hint

        result = _pick_variant_by_hint(
            variants=["Corte Señora", "Corte de Hombre"],
            hint="baby",
        )
        assert result is None

    def test_returns_first_matching_variant(self):
        """S6: Multiple matching variants → returns the first one."""
        from shared.audience_maps import _pick_variant_by_hint

        # Two female variants — should return first match
        result = _pick_variant_by_hint(
            variants=["Tintura Señora", "Corte Señora"],
            hint="adult_female",
        )
        assert result == "Tintura Señora"
