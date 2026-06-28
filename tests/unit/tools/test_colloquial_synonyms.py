"""RED tests — colloquial synonym map (multi-service-resolution, PR 1).

Phase 2 tasks: 2.1 (RED), 2.2 (non-reg annotation), 2.3 (GREEN impl).

The synonym map resolves colloquial hairdressing terms to internal Service.name
strings BEFORE the by_internal / by_display / diminutive lookup chain so the
existing _AUDIENCE_SUFFIX_REPLACEMENTS double-transform is bypassed.

Key invariants this test file pins:
  - "pelado", "rapado", "pelao", "rapadito" → "Corte de Hombre" in one call
  - audience self-pins to adult_male from the internal name → no audience_required
  - already-known catalog terms are unaffected
  - truly unknown terms still go to unknown_names (PR 2 handles the fallback)

These tests FAIL until _COLLOQUIAL_SYNONYM_MAP is added to _booking_helpers.py
and wired into _resolve_service_ids_strict (task 2.3).

Refs: spec §service-resolution, design ADR-2.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Shared catalog fixtures
# ---------------------------------------------------------------------------

_CORTE_DE_HOMBRE_UUID = uuid4()
_CORTE_DE_MUJER_UUID = uuid4()


def _single_principal_catalog():
    """Catalog with only Corte de Hombre — minimal for synonym resolution."""
    return [
        (
            _CORTE_DE_HOMBRE_UUID,
            "Corte de Hombre",
            "adult_male",
            {"service_type": "principal", "dimension": "cut"},
        ),
    ]


def _multi_audience_catalog():
    """Catalog with Corte de Mujer + Corte de Hombre — tests audience self-pin."""
    return [
        (
            _CORTE_DE_MUJER_UUID,
            "Corte de Mujer",
            "adult_female",
            {"service_type": "principal", "dimension": "cut"},
        ),
        (
            _CORTE_DE_HOMBRE_UUID,
            "Corte de Hombre",
            "adult_male",
            {"service_type": "principal", "dimension": "cut"},
        ),
    ]


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _SeqSession:
    """Async session stub returning canned results in call order; falls back to empty."""

    def __init__(self, results: list[_Result]):
        self._queue = list(results)

    async def execute(self, *_args, **_kwargs):
        if self._queue:
            return self._queue.pop(0)
        return _Result([])  # safe fallback for extra calls


# ---------------------------------------------------------------------------
# Pure map tests — no DB needed
# ---------------------------------------------------------------------------


class TestColloquialSynonymMapShape:
    """_COLLOQUIAL_SYNONYM_MAP must exist as a dict with the expected seed entries.

    These tests are RED until task 2.3 adds the map to _booking_helpers.py.
    """

    def test_map_is_importable(self):
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP  # noqa: F401

    def test_map_is_dict(self):
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        assert isinstance(_COLLOQUIAL_SYNONYM_MAP, dict)

    def test_pelado_in_map(self):
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        assert "pelado" in _COLLOQUIAL_SYNONYM_MAP

    def test_rapado_in_map(self):
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        assert "rapado" in _COLLOQUIAL_SYNONYM_MAP

    def test_pelao_in_map(self):
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        assert "pelao" in _COLLOQUIAL_SYNONYM_MAP

    def test_rapadito_in_map(self):
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        assert "rapadito" in _COLLOQUIAL_SYNONYM_MAP

    def test_pelado_maps_to_corte_de_hombre(self):
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        assert _COLLOQUIAL_SYNONYM_MAP["pelado"] == "Corte de Hombre"

    def test_rapado_maps_to_corte_de_hombre(self):
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        assert _COLLOQUIAL_SYNONYM_MAP["rapado"] == "Corte de Hombre"

    def test_map_values_are_internal_names_not_display(self):
        """Values must be internal Service.name strings, NOT customer-safe display names.

        Design ADR-2: if values were display names (e.g. 'corte de caballero'), the
        by_display lookup would succeed but _AUDIENCE_SUFFIX_REPLACEMENTS would have
        already transformed the name, preventing correct audience inference.
        """
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        for term, internal_name in _COLLOQUIAL_SYNONYM_MAP.items():
            assert "caballero" not in internal_name.lower(), (
                f"Synonym map value '{internal_name}' (key '{term}') looks like a display name, "
                "not an internal Service.name — must be 'Corte de Hombre', not 'corte de caballero'."
            )


# ---------------------------------------------------------------------------
# Integration tests — mocked DB
# ---------------------------------------------------------------------------


class TestColloquialSynonymResolution:
    """Full _resolve_service_ids_strict path with mocked session.

    These tests are RED until task 2.3 wires _COLLOQUIAL_SYNONYM_MAP into the loop.
    """

    @pytest.mark.asyncio
    async def test_pelado_resolves_to_corte_de_hombre_uuid(self):
        """'pelado' must resolve to Corte de Hombre UUID in ONE call, no unknown_names."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _resolve_service_ids_strict

            session = _SeqSession(
                [
                    _Result(_single_principal_catalog()),  # initial catalog fetch
                    # _resolve_audience_variants metadata → None → early return
                ]
            )
            resolved, unknown, ambiguous, partial = await _resolve_service_ids_strict(
                session, ["pelado"]
            )

        assert resolved == [
            str(_CORTE_DE_HOMBRE_UUID)
        ], f"Expected UUID in resolved, got {resolved}"
        assert unknown == [], f"'pelado' must not be in unknown_names: {unknown}"
        assert ambiguous == [], f"No ambiguity expected: {ambiguous}"

    @pytest.mark.asyncio
    async def test_rapado_resolves_to_corte_de_hombre_uuid(self):
        """'rapado' resolves identically to 'pelado'."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _resolve_service_ids_strict

            session = _SeqSession([_Result(_single_principal_catalog())])
            resolved, unknown, ambiguous, partial = await _resolve_service_ids_strict(
                session, ["rapado"]
            )

        assert resolved == [str(_CORTE_DE_HOMBRE_UUID)]
        assert unknown == []
        assert ambiguous == []

    @pytest.mark.asyncio
    async def test_pelao_resolves_to_corte_de_hombre_uuid(self):
        """Argentinian shortening 'pelao' resolves without round-trip."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _resolve_service_ids_strict

            session = _SeqSession([_Result(_single_principal_catalog())])
            resolved, unknown, ambiguous, partial = await _resolve_service_ids_strict(
                session, ["pelao"]
            )

        assert resolved == [str(_CORTE_DE_HOMBRE_UUID)]
        assert unknown == []
        assert ambiguous == []

    @pytest.mark.asyncio
    async def test_rapadito_resolves_to_corte_de_hombre_uuid(self):
        """Diminutive 'rapadito' is in the map and resolves without diminutive stripping."""
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _resolve_service_ids_strict

            session = _SeqSession([_Result(_single_principal_catalog())])
            resolved, unknown, ambiguous, partial = await _resolve_service_ids_strict(
                session, ["rapadito"]
            )

        assert resolved == [str(_CORTE_DE_HOMBRE_UUID)]
        assert unknown == []
        assert ambiguous == []

    @pytest.mark.asyncio
    async def test_synonym_self_pins_adult_male_no_audience_required(self):
        """'pelado' via synonym → 'Corte de Hombre' self-pins audience=adult_male.

        With a multi-audience catalog (Corte de Mujer + Corte de Hombre), a neutral
        family term normally triggers audience_required. But 'pelado' maps to the
        SPECIFIC gendered principal and then infers adult_male from the internal name,
        so the audience gate MUST NOT fire — no audience_required in ambiguous.

        RED: before task 2.3 adds the map + audience-inference fallback, 'pelado'
        goes to unknown_names and this assertion fails.
        """
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _resolve_service_ids_strict

            # Provide metadata for "Corte de Hombre" so _resolve_audience_variants
            # can confirm it's a principal; input_audience=adult_male prevents gate.
            session = _SeqSession(
                [
                    _Result(_multi_audience_catalog()),  # call 1: initial catalog fetch
                    _Result(
                        [({"service_type": "principal", "dimension": "cut"}, "adult_male")]
                    ),  # call 2: _resolve_audience_variants metadata
                    _Result([]),  # call 3: children check
                    _Result(
                        [("Corte de Mujer", "adult_female"), ("Corte de Hombre", "adult_male")]
                    ),  # call 4: peers (input_audience != None → gate doesn't fire)
                ]
            )
            resolved, unknown, ambiguous, partial = await _resolve_service_ids_strict(
                session, ["pelado"]
            )

        assert resolved == [
            str(_CORTE_DE_HOMBRE_UUID)
        ], f"Expected UUID in resolved, got {resolved}"
        assert unknown == []
        audience_hints = [d.get("question_hint") for d in ambiguous]
        assert (
            "audience_required" not in audience_hints
        ), f"audience_required must not fire for synonym-resolved 'pelado', got: {ambiguous}"

    @pytest.mark.asyncio
    async def test_known_catalog_name_unaffected_by_synonym_map(self):
        """A term already in the catalog ('corte de hombre' display match) bypasses synonym map.

        Non-regression: the synonym map must not break existing exact-match resolution.
        """
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _resolve_service_ids_strict

            session = _SeqSession([_Result(_single_principal_catalog())])
            # "Corte de Hombre" is the internal name — resolves directly via by_internal.
            resolved, unknown, ambiguous, partial = await _resolve_service_ids_strict(
                session, ["Corte de Hombre"]
            )

        assert resolved == [str(_CORTE_DE_HOMBRE_UUID)]
        assert unknown == []
        assert ambiguous == []

    @pytest.mark.asyncio
    async def test_truly_unknown_term_still_goes_to_unknown(self):
        """A term absent from both catalog and synonym map goes to unknown_names.

        PR 2 will replace this with the suggestion fallback; PR 1 must not change
        this behavior (unknown_names must remain non-empty for truly unknown terms).
        """
        with patch(
            "agent.prompts.catalog_builder._derive_customer_safe_service_name",
            side_effect=lambda name: name.lower() if name else "",
        ):
            from agent.tools._booking_helpers import _resolve_service_ids_strict

            session = _SeqSession([_Result(_single_principal_catalog())])
            resolved, unknown, ambiguous, partial = await _resolve_service_ids_strict(
                session, ["xyz123-nosuchservice"]
            )

        assert unknown == ["xyz123-nosuchservice"]
        assert resolved == []


# ---------------------------------------------------------------------------
# Non-regression: neutral "corte" still yields audience_required (task 2.2)
# ---------------------------------------------------------------------------


class TestNeutralCorteNonRegression:
    """Neutral 'corte' must NOT be accidentally caught by the synonym map.

    The map only contains specific terms like 'pelado'; bare 'corte' must still
    flow through the existing audience-family fallback and yield audience_required.

    This test documents the invariant and must stay GREEN before and after PR 1.
    Refs: test_audience_family_gate.py::test_resolver_neutral_corte_yields_audience_required_not_unknown
    """

    @pytest.mark.asyncio
    async def test_neutral_corte_not_in_synonym_map(self):
        """'corte' must not be a key in _COLLOQUIAL_SYNONYM_MAP."""
        from agent.tools._booking_helpers import _COLLOQUIAL_SYNONYM_MAP

        assert "corte" not in _COLLOQUIAL_SYNONYM_MAP, (
            "'corte' must not be in the synonym map — it must go through "
            "the audience-family gate and return audience_required."
        )
