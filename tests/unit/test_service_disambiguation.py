"""
Unit tests for agent/services/service_disambiguation.py.

These tests exercise the resolve_candidates() function in pure-Python mode —
no database, no async. Service objects are constructed as plain mocks so the
tests stay fast and deterministic.

Test cases:
    1. Ambiguous family (Mechas) with no axes → ClarificationPayload for hair_density
    2. Ambiguous family (Mechas) with hair_density provided → ResolvedService
    3. No metadata (empty {}) on all candidates → candidates returned unchanged (fallback)
    4. All candidates have family but hair_length disambiguates (Peinado)
    5. Single candidate with metadata → resolves directly
    6. Empty candidate list → empty list returned
    7. Mixed: some with metadata, some without → uses metadata group
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from agent.utils.service_disambiguation import (
    ClarificationPayload,
    ResolvedService,
    _AXIS_QUESTION_HINTS,
    _AXIS_VALUE_LABELS,
    _to_resolved,
    resolve_candidates,
)
from database.models import ServiceCategory


# ---------------------------------------------------------------------------
# Helpers to build fake Service objects
# ---------------------------------------------------------------------------


def _make_service(
    name: str,
    duration_minutes: int = 60,
    description: str | None = None,
    metadata_: dict | None = None,
) -> MagicMock:
    """Build a minimal mock that satisfies the resolve_candidates() interface."""
    svc = MagicMock()
    svc.id = _uuid_for(name)
    svc.name = name
    svc.duration_minutes = duration_minutes
    svc.description = description
    svc.category = ServiceCategory.HAIRDRESSING
    svc.metadata_ = metadata_ or {}
    return svc


def _uuid_for(name: str) -> UUID:
    """Deterministic UUID from a service name (for test identity checks)."""
    import hashlib

    h = hashlib.sha256(name.encode()).hexdigest()[:32]
    return UUID(h)


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

MECHAS_STANDARD = _make_service(
    "Mechas",
    duration_minutes=60,
    metadata_={
        "family": "highlights",
        "audience": None,
        "disambiguation_tags": ["mechas", "highlights"],
        "ask_if_missing": ["hair_density"],
        "variant": "standard",
        "hair_length": None,
        "hair_density": "normal",
        "combo_recommendations": [],
    },
)

MECHAS_EXTRAS = _make_service(
    "Mechas Extras",
    duration_minutes=70,
    metadata_={
        "family": "highlights",
        "audience": None,
        "disambiguation_tags": ["mechas extras", "mechas extra"],
        "ask_if_missing": [],
        "variant": "extra",
        "hair_length": None,
        "hair_density": "extra",
        "combo_recommendations": [],
    },
)

PEINADO_STANDARD = _make_service(
    "Peinado",
    duration_minutes=40,
    metadata_={
        "family": "hairstyle",
        "audience": None,
        "disambiguation_tags": ["peinado", "blow dry"],
        "ask_if_missing": ["hair_length"],
        "variant": "standard",
        "hair_length": "short_medium",
        "hair_density": None,
        "combo_recommendations": [],
    },
)

PEINADO_LARGO = _make_service(
    "Peinado Largo",
    duration_minutes=45,
    metadata_={
        "family": "hairstyle",
        "audience": None,
        "disambiguation_tags": ["peinado largo"],
        "ask_if_missing": [],
        "variant": "long",
        "hair_length": "long",
        "hair_density": None,
        "combo_recommendations": [],
    },
)

CORTE_CABALLERO = _make_service(
    "Corte Caballero",
    duration_minutes=40,
    metadata_={
        "family": "haircut",
        "audience": "adult_male",
        "disambiguation_tags": ["corte caballero", "caballero", "hombre"],
        "ask_if_missing": [],
        "variant": None,
        "hair_length": None,
        "hair_density": None,
        "combo_recommendations": ["Barba"],
    },
)

# Service without disambiguation metadata
BIOTERAPIA_FACIAL = _make_service(
    "Bioterapia Facial Completa",
    duration_minutes=90,
    metadata_={},
)

BIOTERAPIA_ESCULTOR = _make_service(
    "Bioterapia Escultor",
    duration_minutes=60,
    metadata_={},
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolveCandidates:
    """Tests for resolve_candidates()."""

    # -----------------------------------------------------------------------
    # 1. Ambiguous family → ClarificationPayload
    # -----------------------------------------------------------------------

    def test_ambiguous_highlights_family_returns_clarification(self):
        """
        Mechas + Mechas Extras in same family with no axes supplied →
        should return ClarificationPayload asking about hair_density.
        """
        result = resolve_candidates([MECHAS_STANDARD, MECHAS_EXTRAS])

        assert isinstance(result, ClarificationPayload), (
            f"Expected ClarificationPayload, got {type(result)}"
        )
        assert result.axis == "hair_density"
        assert result.question_hint  # non-empty
        assert len(result.options) == 2  # normal + extra

        option_values = {opt["value"] for opt in result.options}
        assert option_values == {"normal", "extra"}

    def test_clarification_options_contain_required_fields(self):
        """Each option in ClarificationPayload must have all required fields."""
        result = resolve_candidates([MECHAS_STANDARD, MECHAS_EXTRAS])

        assert isinstance(result, ClarificationPayload)
        for opt in result.options:
            assert "label" in opt
            assert "value" in opt
            assert "service_name" in opt
            assert "service_id" in opt
            assert "duration_minutes" in opt

    def test_peinado_family_requests_hair_length(self):
        """
        Peinado + Peinado Largo in same family with no axes →
        should clarify on hair_length.
        """
        result = resolve_candidates([PEINADO_STANDARD, PEINADO_LARGO])

        assert isinstance(result, ClarificationPayload)
        assert result.axis == "hair_length"
        option_values = {opt["value"] for opt in result.options}
        assert "short_medium" in option_values
        assert "long" in option_values

    # -----------------------------------------------------------------------
    # 2. Axis provided → ResolvedService
    # -----------------------------------------------------------------------

    def test_mechas_with_hair_density_normal_resolves(self):
        """
        Providing hair_density='normal' for Mechas family →
        should resolve to 'Mechas' (standard variant).
        """
        result = resolve_candidates(
            [MECHAS_STANDARD, MECHAS_EXTRAS],
            hair_density="normal",
        )

        assert isinstance(result, ResolvedService), f"Expected ResolvedService, got {type(result)}"
        assert result.name == "Mechas"
        assert result.duration_minutes == 60
        assert result.family == "highlights"

    def test_mechas_with_hair_density_extra_resolves(self):
        """
        Providing hair_density='extra' for Mechas family →
        should resolve to 'Mechas Extras'.
        """
        result = resolve_candidates(
            [MECHAS_STANDARD, MECHAS_EXTRAS],
            hair_density="extra",
        )

        assert isinstance(result, ResolvedService)
        assert result.name == "Mechas Extras"
        assert result.duration_minutes == 70

    def test_peinado_with_hair_length_long_resolves(self):
        """Providing hair_length='long' → resolves to Peinado Largo."""
        result = resolve_candidates(
            [PEINADO_STANDARD, PEINADO_LARGO],
            hair_length="long",
        )

        assert isinstance(result, ResolvedService)
        assert result.name == "Peinado Largo"
        assert result.duration_minutes == 45

    def test_resolved_service_id_matches_database_id(self):
        """ResolvedService.id must equal the original Service.id."""
        result = resolve_candidates([MECHAS_STANDARD, MECHAS_EXTRAS], hair_density="normal")

        assert isinstance(result, ResolvedService)
        assert result.id == MECHAS_STANDARD.id

    # -----------------------------------------------------------------------
    # 3. No metadata → fallback (return candidates unchanged)
    # -----------------------------------------------------------------------

    def test_no_metadata_returns_candidates_unchanged(self):
        """
        When ALL candidates have metadata_ == {} (no family), the function
        must return the original list unchanged (fallback path).
        """
        candidates = [BIOTERAPIA_FACIAL, BIOTERAPIA_ESCULTOR]
        result = resolve_candidates(candidates)

        assert result is candidates or result == candidates, (
            "Expected original candidates list to be returned unchanged"
        )
        # Ensure we do NOT get a ResolvedService or ClarificationPayload
        assert not isinstance(result, ResolvedService)
        assert not isinstance(result, ClarificationPayload)

    def test_single_no_metadata_candidate_returned_unchanged(self):
        """Single candidate without metadata → returned unchanged."""
        candidates = [BIOTERAPIA_FACIAL]
        result = resolve_candidates(candidates)

        # Should NOT resolve to ResolvedService without metadata
        assert isinstance(result, list)
        assert len(result) == 1

    # -----------------------------------------------------------------------
    # 4. Single candidate with metadata → resolved directly
    # -----------------------------------------------------------------------

    def test_single_candidate_with_metadata_resolves_directly(self):
        """Single candidate with family metadata → resolved without clarification."""
        result = resolve_candidates([CORTE_CABALLERO])

        assert isinstance(result, ResolvedService)
        assert result.name == "Corte Caballero"
        assert result.id == CORTE_CABALLERO.id

    # -----------------------------------------------------------------------
    # 5. Edge cases
    # -----------------------------------------------------------------------

    def test_empty_candidate_list_returns_empty_list(self):
        """Empty candidate list → empty list returned (no crash)."""
        result = resolve_candidates([])

        assert result == []

    def test_resolved_service_contains_combo_recommendations(self):
        """ResolvedService should carry combo_recommendations from metadata."""
        result = resolve_candidates([CORTE_CABALLERO])

        assert isinstance(result, ResolvedService)
        assert "Barba" in result.combo_recommendations

    def test_resolved_service_ask_if_missing_empty_when_resolved(self):
        """
        When disambiguated by providing the axis, ask_if_missing on the
        resulting ResolvedService should reflect the service's own metadata.
        """
        result = resolve_candidates([MECHAS_STANDARD, MECHAS_EXTRAS], hair_density="normal")

        assert isinstance(result, ResolvedService)
        # MECHAS_STANDARD has ask_if_missing: ["hair_density"]
        assert isinstance(result.ask_if_missing, list)

    # -----------------------------------------------------------------------
    # 6. Mixed metadata/no-metadata candidates
    # -----------------------------------------------------------------------

    def test_mixed_candidates_uses_metadata_group(self):
        """
        When candidates include both services with metadata and without,
        the resolver should use the metadata group for disambiguation.
        """
        # Bioterapia has no family; Mechas family has hair_density ambiguity
        result = resolve_candidates([MECHAS_STANDARD, MECHAS_EXTRAS, BIOTERAPIA_FACIAL])

        # Should return ClarificationPayload for the Mechas family
        assert isinstance(result, ClarificationPayload)
        assert result.axis == "hair_density"


class TestResolvedServiceDescription:
    def test_resolved_service_accepts_missing_description(self):
        resolved = ResolvedService(
            id=_uuid_for("x"),
            name="Corte",
            duration_minutes=30,
            category="Peluquería",
            family=None,
            ask_if_missing=[],
            combo_recommendations=[],
        )

        assert resolved.description is None

    def test_resolved_service_preserves_provided_description(self):
        resolved = ResolvedService(
            id=_uuid_for("x"),
            name="Corte",
            duration_minutes=30,
            category="Peluquería",
            family=None,
            ask_if_missing=[],
            combo_recommendations=[],
            description="Corte clásico",
        )

        assert resolved.description == "Corte clásico"

    def test_resolved_service_description_defaults_to_none(self):
        resolved = ResolvedService(
            id=_uuid_for("Corte"),
            name="Corte",
            duration_minutes=45,
            category=ServiceCategory.HAIRDRESSING.value,
            family="haircut",
        )

        assert resolved.description is None

    def test_to_resolved_populates_description_when_service_has_one(self):
        service = _make_service(
            "Cortar",
            duration_minutes=40,
            description="Corte capilar completo con lavado incluido",
            metadata_={"family": "haircut", "combo_recommendations": []},
        )

        resolved = _to_resolved(service)

        assert resolved.description == "Corte capilar completo con lavado incluido"


# ---------------------------------------------------------------------------
# Axis labels and question hints
# ---------------------------------------------------------------------------


def test_audience_labels_are_colloquial():
    """Labels de audiencia deben ser coloquiales, no vocabulario técnico de peluquería."""
    labels = _AXIS_VALUE_LABELS["audience"]
    assert labels["adult_male"] == "Hombre"
    assert labels["adult_female"] == "Mujer"
    assert "Caballero" not in labels.values()
    assert "Dama / Señora" not in labels.values()


def test_audience_question_hint_is_short():
    """El hint de audiencia debe ser corto y coloquial."""
    hint = _AXIS_QUESTION_HINTS["audience"]
    assert hint == "¿Para quién es el corte?"
    assert "caballero" not in hint.lower()
    assert "dama" not in hint.lower()
