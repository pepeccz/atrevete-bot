"""RED tests — Phase 4: candidate-selection heuristic (multi-service-resolution PR 2).

_find_catalog_candidates(session, unknown_terms) must return a SHORT
dimension-aware shortlist of real catalog service names. For a cut-like term
("pelado", "rapado", "peluqueria") it returns Corte de… names, not random or
irrelevant services like Tinte or Mechas.

_DIMENSION_KEYWORD_MAP must exist as a module-level dict seeding the keyword→
dimension inference.

These tests FAIL until task 4.2 adds both symbols to _booking_helpers.py.

Refs: design ADR-1, spec §unknown-service-suggestion.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Mock session infrastructure (same pattern as test_colloquial_synonyms.py)
# ---------------------------------------------------------------------------

_CUT_UUID_1 = uuid4()
_CUT_UUID_2 = uuid4()
_CUT_UUID_3 = uuid4()
_CUT_UUID_4 = uuid4()
_COLOR_UUID = uuid4()
_HIGHLIGHTS_UUID = uuid4()
_MANICURE_UUID = uuid4()
_WAX_UUID = uuid4()


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _SeqSession:
    """Async session stub — returns canned results in call order."""

    def __init__(self, results: list[_Result]):
        self._queue = list(results)

    async def execute(self, *_args, **_kwargs):
        if self._queue:
            return self._queue.pop(0)
        return _Result([])


def _full_catalog():
    """Catalog with cut (4), color (1), highlights (1), manicure (1), wax (1) principals."""
    return [
        # Cut dimension — 4 principals
        (
            _CUT_UUID_1,
            "Corte de Mujer",
            {"service_type": "principal", "dimension": "cut"},
        ),
        (
            _CUT_UUID_2,
            "Corte de Hombre",
            {"service_type": "principal", "dimension": "cut"},
        ),
        (
            _CUT_UUID_3,
            "Corte de Niño",
            {"service_type": "principal", "dimension": "cut"},
        ),
        (
            _CUT_UUID_4,
            "Corte de Niña",
            {"service_type": "principal", "dimension": "cut"},
        ),
        # Color
        (
            _COLOR_UUID,
            "Tinte",
            {"service_type": "principal", "dimension": "color"},
        ),
        # Highlights
        (
            _HIGHLIGHTS_UUID,
            "Mechas",
            {"service_type": "principal", "dimension": "highlights"},
        ),
        # Manicure
        (
            _MANICURE_UUID,
            "Manicura",
            {"service_type": "principal", "dimension": "manicure"},
        ),
        # Wax
        (
            _WAX_UUID,
            "Depilación",
            {"service_type": "principal", "dimension": "wax"},
        ),
        # Variant — must NOT appear in candidates (only principals)
        (
            uuid4(),
            "Mechas Localizadas",
            {"service_type": "variant", "dimension": "highlights", "parent_service_name": "Mechas"},
        ),
    ]


# ---------------------------------------------------------------------------
# Pure map tests — RED until task 4.2 adds _DIMENSION_KEYWORD_MAP
# ---------------------------------------------------------------------------


class TestDimensionKeywordMap:
    """_DIMENSION_KEYWORD_MAP must exist and seed the heuristic correctly."""

    def test_map_is_importable(self):
        """RED: _DIMENSION_KEYWORD_MAP not yet defined in _booking_helpers."""
        from agent.tools._booking_helpers import _DIMENSION_KEYWORD_MAP  # noqa: F401

    def test_map_is_dict(self):
        from agent.tools._booking_helpers import _DIMENSION_KEYWORD_MAP

        assert isinstance(_DIMENSION_KEYWORD_MAP, dict)

    def test_cut_dimension_has_pel_keyword(self):
        """'pel' must trigger cut dimension so 'pelado' resolves to cut principals."""
        from agent.tools._booking_helpers import _DIMENSION_KEYWORD_MAP

        cut_keywords = [kw.lower() for kw in _DIMENSION_KEYWORD_MAP.get("cut", [])]
        assert "pel" in cut_keywords, (
            "keyword 'pel' missing from 'cut' dimension — 'pelado' won't resolve to "
            "cut-dimension candidates"
        )

    def test_cut_dimension_has_rap_keyword(self):
        from agent.tools._booking_helpers import _DIMENSION_KEYWORD_MAP

        cut_keywords = [kw.lower() for kw in _DIMENSION_KEYWORD_MAP.get("cut", [])]
        assert "rap" in cut_keywords

    def test_cut_dimension_has_corte_keyword(self):
        from agent.tools._booking_helpers import _DIMENSION_KEYWORD_MAP

        cut_keywords = [kw.lower() for kw in _DIMENSION_KEYWORD_MAP.get("cut", [])]
        assert "corte" in cut_keywords

    def test_color_dimension_has_tinte_keyword(self):
        from agent.tools._booking_helpers import _DIMENSION_KEYWORD_MAP

        color_keywords = [kw.lower() for kw in _DIMENSION_KEYWORD_MAP.get("color", [])]
        assert "tinte" in color_keywords

    def test_wax_dimension_has_depil_keyword(self):
        from agent.tools._booking_helpers import _DIMENSION_KEYWORD_MAP

        wax_keywords = [kw.lower() for kw in _DIMENSION_KEYWORD_MAP.get("wax", [])]
        assert "depil" in wax_keywords


# ---------------------------------------------------------------------------
# _find_catalog_candidates function — RED until task 4.2 adds it
# ---------------------------------------------------------------------------


class TestFindCatalogCandidatesImport:
    def test_function_is_importable(self):
        """RED: _find_catalog_candidates not yet defined in _booking_helpers."""
        from agent.tools._booking_helpers import _find_catalog_candidates  # noqa: F401

    def test_function_is_callable(self):
        from agent.tools._booking_helpers import _find_catalog_candidates

        assert callable(_find_catalog_candidates)


class TestFindCatalogCandidatesCutDimension:
    """For cut-like unknown terms, candidates must be cut-dimension principals only."""

    @pytest.mark.asyncio
    async def test_pelado_returns_cut_principals(self):
        """'pelado' → dimension=cut via 'pel' keyword → only Corte de … names."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result(_full_catalog())])
            candidates = await _find_catalog_candidates(session, ["pelado"])

        # Must return some cut-dimension candidates
        assert len(candidates) >= 1, "Expected at least 1 candidate for 'pelado'"
        assert len(candidates) <= 5, f"Must return at most 5 candidates, got {len(candidates)}"

        # All results should be cut principals (all start with "corte de")
        for c in candidates:
            assert c.startswith("corte de"), (
                f"Candidate '{c}' is not a cut-dimension principal — "
                "'pelado' must only yield Corte de… names"
            )

    @pytest.mark.asyncio
    async def test_pelado_does_not_return_tinte(self):
        """'pelado' must NOT yield 'Tinte' or any color-dimension service."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result(_full_catalog())])
            candidates = await _find_catalog_candidates(session, ["pelado"])

        names_lower = [c.lower() for c in candidates]
        assert (
            "tinte" not in names_lower
        ), "Candidate 'tinte' must not appear for the cut-adjacent term 'pelado'"
        assert (
            "mechas" not in names_lower
        ), "Candidate 'mechas' must not appear for the cut-adjacent term 'pelado'"
        assert (
            "manicura" not in names_lower
        ), "Candidate 'manicura' must not appear for the cut-adjacent term 'pelado'"

    @pytest.mark.asyncio
    async def test_rapado_returns_cut_principals(self):
        """'rapado' → dimension=cut via 'rap' keyword → only Corte de … names."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result(_full_catalog())])
            candidates = await _find_catalog_candidates(session, ["rapado"])

        assert len(candidates) >= 1, "Expected at least 1 candidate for 'rapado'"
        for c in candidates:
            assert c.startswith(
                "corte de"
            ), f"Candidate '{c}' is not a cut-dimension principal for 'rapado'"

    @pytest.mark.asyncio
    async def test_variants_excluded_from_candidates(self):
        """Variants (service_type != 'principal') must never appear in candidates."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result(_full_catalog())])
            candidates = await _find_catalog_candidates(session, ["pelado"])

        names_lower = [c.lower() for c in candidates]
        assert "mechas localizadas" not in names_lower, (
            "Variant 'Mechas Localizadas' must not appear in candidates — "
            "only principals are valid suggestions"
        )


class TestFindCatalogCandidatesFallback:
    """When no dimension is inferred, fall back to token-overlap or empty list."""

    @pytest.mark.asyncio
    async def test_unknown_dimension_term_returns_list(self):
        """A completely unknown term (no keyword match) must return a list (possibly empty)."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result(_full_catalog())])
            candidates = await _find_catalog_candidates(session, ["xyzabc123"])

        assert isinstance(candidates, list), "Must always return a list"
        assert len(candidates) <= 5, "Must return at most 5 candidates"

    @pytest.mark.asyncio
    async def test_empty_catalog_returns_empty(self):
        """Empty principal catalog → empty candidates regardless of term."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result([])])
            candidates = await _find_catalog_candidates(session, ["pelado"])

        assert candidates == [], f"Empty catalog must yield [], got: {candidates}"

    @pytest.mark.asyncio
    async def test_empty_terms_returns_empty(self):
        """Empty unknown_terms list → empty candidates."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result(_full_catalog())])
            candidates = await _find_catalog_candidates(session, [])

        assert candidates == [], f"Empty terms must yield [], got: {candidates}"


class TestFindCatalogCandidatesTriangulation:
    """Triangulation: different dimension keywords must yield dimension-correct results."""

    @pytest.mark.asyncio
    async def test_tinte_returns_color_principal(self):
        """'tinte_nuevo' (color keyword 'tinte') → color-dimension candidates."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result(_full_catalog())])
            # Use a mangled name to simulate "unknown service" but preserving the keyword
            candidates = await _find_catalog_candidates(session, ["tinte_nuevo"])

        names_lower = [c.lower() for c in candidates]
        # Color dimension candidate should appear
        assert (
            "tinte" in names_lower
        ), f"Expected 'tinte' in candidates for 'tinte_nuevo', got: {candidates}"
        # Cut-dimension candidates must NOT appear when color keyword is matched
        assert not any(
            c.startswith("corte de") for c in candidates
        ), f"Cut-dimension candidates must not appear for a color-keyed term: {candidates}"

    @pytest.mark.asyncio
    async def test_depilacion_returns_wax_principal(self):
        """Term with 'depil' keyword → wax-dimension candidates."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _find_catalog_candidates

            session = _SeqSession([_Result(_full_catalog())])
            candidates = await _find_catalog_candidates(session, ["depilacion_piernas"])

        names_lower = [c.lower() for c in candidates]
        assert (
            "depilación" in names_lower
        ), f"Expected 'depilación' in candidates for 'depilacion_piernas', got: {candidates}"
