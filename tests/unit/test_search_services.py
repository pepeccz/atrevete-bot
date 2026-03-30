"""
Unit tests for agent/tools/search_services.py.

Tests exercise the updated response envelope which now distinguishes:
  - ``resolved_service``     — single unambiguous metadata-backed match
  - ``clarification_needed`` — ambiguous metadata family, clarification required
  - ``services``             — plain ranked fuzzy matches (no metadata / fallback)

All tests use MagicMock/AsyncMock to avoid hitting the database.
The module is loaded directly (bypassing agent.tools.__init__) so these tests
work both locally (Python 3.14) and in Docker (Python 3.11).
"""

from __future__ import annotations

import sys
import uuid
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from database.models import ServiceCategory

# ---------------------------------------------------------------------------
# Load search_services module directly (bypass agent.tools.__init__)
# because agent.tools.__init__ eagerly imports langchain_core which has
# pydantic.v1 compatibility issues on Python 3.14.
# ---------------------------------------------------------------------------


def _load_search_services_module():
    """
    Load agent/tools/search_services.py as a standalone module, bypassing
    the eagerly-importing agent/tools/__init__.py.

    The module uses `from langchain_core.tools import tool` at import time.
    We stub langchain_core so the @tool decorator becomes a no-op.
    """
    # Prefer the real langchain_core package when available so this module does
    # not poison the rest of the test session with a fake top-level package.
    try:
        import langchain_core.tools  # noqa: F401
    except ImportError:
        if "langchain_core.tools" not in sys.modules:

            def _tool_decorator(fn=None, args_schema=None, **kwargs):
                """Minimal @tool stub that returns the function unchanged."""
                if fn is None:

                    def wrapper(f):
                        # Attach an ainvoke method so tests can call it
                        async def ainvoke(args: dict[str, Any]):
                            return await f(**args)

                        f.ainvoke = ainvoke
                        return f

                    return wrapper

                # Direct decoration (no args)
                async def ainvoke(args: dict[str, Any]):
                    return await fn(**args)

                fn.ainvoke = ainvoke
                return fn

            lc_stub = ModuleType("langchain_core")
            lc_tools_stub = ModuleType("langchain_core.tools")
            lc_tools_stub.tool = _tool_decorator
            sys.modules["langchain_core"] = lc_stub
            sys.modules["langchain_core.tools"] = lc_tools_stub

    import importlib.util
    import os

    # Compute path relative to project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    module_path = os.path.join(project_root, "agent", "tools", "search_services.py")

    spec = importlib.util.spec_from_file_location(
        "agent.tools.search_services_standalone",
        module_path,
    )
    assert isinstance(spec, ModuleSpec)
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load module once at module scope so tests share the same import
_ss_mod = _load_search_services_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    name: str,
    duration_minutes: int = 60,
    description: str | None = None,
    metadata_: dict | None = None,
) -> MagicMock:
    svc = MagicMock()
    svc.id = _uuid_for(name)
    svc.name = name
    svc.duration_minutes = duration_minutes
    svc.description = description
    svc.category = ServiceCategory.HAIRDRESSING
    svc.is_active = True
    svc.metadata_ = metadata_ or {}
    return svc


def _uuid_for(name: str) -> uuid.UUID:
    import hashlib

    h = hashlib.sha256(name.encode()).hexdigest()[:32]
    return uuid.UUID(h)


# -----------------------------------------------------------------------
# Shared service fixtures
# -----------------------------------------------------------------------

MECHAS = _make_service(
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
        "disambiguation_tags": ["mechas extras"],
        "ask_if_missing": [],
        "variant": "extra",
        "hair_length": None,
        "hair_density": "extra",
        "combo_recommendations": [],
    },
)

PEINADO = _make_service(
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
        "disambiguation_tags": ["corte caballero", "caballero"],
        "ask_if_missing": [],
        "variant": None,
        "hair_length": None,
        "hair_density": None,
        "combo_recommendations": ["Barba"],
    },
)

BIOTERAPIA_FACIAL = _make_service(
    "Bioterapia Facial Completa",
    duration_minutes=90,
    metadata_={},  # No disambiguation metadata
)

CORTAR = _make_service(
    "Cortar",
    duration_minutes=40,
    description="Corte capilar completo con lavado incluido",
    metadata_={
        "family": "haircut",
        "audience": "adult_female",
        "disambiguation_tags": [
            "cortar",
            "corte",
            "corte adulto",
            "corte mujer",
            "corte señora",
            "corte dama",
            "mujer adulta",
            "señora",
            "dama",
        ],
        "ask_if_missing": [],
        "variant": None,
        "hair_length": None,
        "hair_density": None,
        "combo_recommendations": [],
    },
)


# ---------------------------------------------------------------------------
# Context manager mock for get_async_session
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal async context manager session stub."""

    def __init__(self, services: list) -> None:
        self._services = services

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, _query):
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._services
        return result


def _patch_db(services: list):
    """Patch get_async_session in the STANDALONE module namespace."""
    return patch.object(
        _ss_mod,
        "get_async_session",
        return_value=_FakeSession(services),
    )


async def _invoke(query: str, category=None, max_results: int = 5) -> dict:
    """Call the search_services function directly via its ainvoke wrapper."""
    args: dict[str, Any] = {"query": query, "max_results": max_results}
    if category is not None:
        args["category"] = category
    return await _ss_mod.search_services.ainvoke(args)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSearchServicesEnvelope:
    """Tests for the updated search_services response envelope."""

    # -----------------------------------------------------------------------
    # clarification_needed cases
    # -----------------------------------------------------------------------

    async def test_mechas_query_returns_clarification_hair_density(self):
        """
        Query 'Mechas' matches both Mechas (normal) and Mechas Extras (extra).
        Should return ``clarification_needed`` with axis='hair_density'.
        """
        with _patch_db([MECHAS, MECHAS_EXTRAS]):
            result = await _invoke("mechas")

        assert (
            "clarification_needed" in result
        ), f"Expected 'clarification_needed' key in result, got: {list(result.keys())}"
        clarification = result["clarification_needed"]
        assert clarification["axis"] == "hair_density"
        assert clarification["question_hint"]
        assert len(clarification["options"]) == 2
        assert result["count"] == 0
        assert result["query"] == "mechas"

    async def test_peinado_query_returns_clarification_hair_length(self):
        """
        Query 'Peinado' matches both Peinado and Peinado Largo.
        Should return ``clarification_needed`` with axis='hair_length'.
        """
        with _patch_db([PEINADO, PEINADO_LARGO]):
            result = await _invoke("peinado")

        assert "clarification_needed" in result
        clarification = result["clarification_needed"]
        assert clarification["axis"] == "hair_length"

        option_values = {opt["value"] for opt in clarification["options"]}
        assert "short_medium" in option_values
        assert "long" in option_values

    async def test_clarification_options_have_service_id_and_duration(self):
        """Each clarification option must expose service_id and duration_minutes."""
        with _patch_db([MECHAS, MECHAS_EXTRAS]):
            result = await _invoke("mechas")

        clarification = result["clarification_needed"]
        for opt in clarification["options"]:
            assert "service_id" in opt
            assert "duration_minutes" in opt
            assert "service_name" in opt
            assert "label" in opt

    # -----------------------------------------------------------------------
    # resolved_service cases
    # -----------------------------------------------------------------------

    async def test_corte_caballero_returns_resolved_service(self):
        """
        Query 'corte caballero' hits a single service in the haircut family with
        audience=adult_male and no ask_if_missing axes — should resolve directly.
        """
        with _patch_db([CORTE_CABALLERO]):
            result = await _invoke("corte caballero")

        assert (
            "resolved_service" in result
        ), f"Expected 'resolved_service' key in result, got: {list(result.keys())}"
        resolved = result["resolved_service"]
        assert resolved["name"] == "Corte Caballero"
        assert resolved["duration_minutes"] == 40
        assert "id" in resolved
        assert result["count"] == 1


class TestMetadataAwareScoring:
    @pytest.mark.parametrize("query", ["corte mujer", "dama", "señora", "mujer adulta"])
    def test_female_haircut_queries_score_cortar_above_cutoff(self, query: str):
        score = _ss_mod._calculate_service_score(query, CORTAR)

        assert score >= 60

    def test_female_haircut_query_ranks_cortar_above_corte_caballero(self):
        cortar_score = _ss_mod._calculate_service_score("corte mujer", CORTAR)
        caballero_score = _ss_mod._calculate_service_score("corte mujer", CORTE_CABALLERO)

        assert cortar_score > caballero_score
        assert cortar_score >= 60

    def test_corte_caballero_query_keeps_male_haircut_ranked_above_cortar(self):
        caballero_score = _ss_mod._calculate_service_score("corte caballero", CORTE_CABALLERO)
        cortar_score = _ss_mod._calculate_service_score("corte caballero", CORTAR)

        assert caballero_score > cortar_score

    def test_existing_good_paths_still_score_above_cutoff(self):
        assert _ss_mod._calculate_service_score("mechas", MECHAS) >= 60
        assert _ss_mod._calculate_service_score("peinado", PEINADO) >= 60

    @pytest.mark.parametrize(
        ("query", "service"),
        [
            ("mechas", MECHAS),
            ("peinado", PEINADO),
            ("corte caballero", CORTE_CABALLERO),
        ],
    )
    def test_phase5_regression_queries_keep_expected_services_above_cutoff(
        self, query: str, service: MagicMock
    ):
        assert _ss_mod._calculate_service_score(query, service) >= 60

    @pytest.mark.parametrize("query", ["mujer adulta", "corte dama", "corte señora"])
    async def test_phase5_adult_female_synonyms_resolve_cortar(self, query: str):
        with _patch_db([CORTAR, CORTE_CABALLERO]):
            result = await _invoke(query)

        assert "resolved_service" in result
        assert result["resolved_service"]["name"] == "Cortar"

    def test_phase5_scoring_uses_bounded_similarity_calls(self):
        tag_count = len(CORTAR.metadata_["disambiguation_tags"])
        with patch.object(_ss_mod.fuzz, "token_set_ratio", return_value=80) as mocked_ratio:
            score = _ss_mod._calculate_service_score("corte dama", CORTAR)

        assert score >= 60
        assert mocked_ratio.call_count == tag_count + 2

    async def test_resolved_service_has_id_field(self):
        """resolved_service envelope must include id (restored in v3.2)."""
        with _patch_db([CORTE_CABALLERO]):
            result = await _invoke("corte caballero")

        resolved = result["resolved_service"]
        assert "id" in resolved
        assert resolved["id"] == str(CORTE_CABALLERO.id)

    async def test_resolved_service_includes_description_key(self):
        with _patch_db([CORTAR]):
            result = await _invoke("cortar")

        resolved = result["resolved_service"]
        assert "description" in resolved
        assert resolved["description"] == CORTAR.description

    # -----------------------------------------------------------------------
    # services (fallback) cases
    # -----------------------------------------------------------------------

    async def test_bioterapia_facial_returns_services_fallback(self):
        """
        Query for a service without metadata should fall through to ranked
        ``services`` list (no metadata disambiguation attempted).
        """
        with _patch_db([BIOTERAPIA_FACIAL]):
            result = await _invoke("bioterapia facial")

        assert (
            "services" in result
        ), f"Expected 'services' key in result, got: {list(result.keys())}"
        services = result["services"]
        assert len(services) >= 1
        # Should NOT be clarification or resolved_service
        assert "clarification_needed" not in result
        assert "resolved_service" not in result

    async def test_services_list_includes_id_field(self):
        """
        The ``services`` fallback list must include ``id`` (restored in v3.2)
        so the booking flow can use service IDs directly.
        """
        with _patch_db([BIOTERAPIA_FACIAL]):
            result = await _invoke("bioterapia")

        if "services" in result and result["services"]:
            for svc in result["services"]:
                assert "id" in svc, f"Missing 'id' field in service result: {svc}"

    # -----------------------------------------------------------------------
    # No match case
    # -----------------------------------------------------------------------

    async def test_no_match_returns_empty_services(self):
        """When no services match the query, returns empty services list with message."""
        with _patch_db([MECHAS, CORTE_CABALLERO, BIOTERAPIA_FACIAL]):
            # Query that won't match anything meaningful
            result = await _invoke("xyzzy_no_match_zzz")

        assert result.get("count", 0) == 0
        # Either empty services list or message key
        if "services" in result:
            assert result["services"] == []

    # -----------------------------------------------------------------------
    # Error case
    # -----------------------------------------------------------------------

    async def test_db_error_returns_error_envelope(self):
        """When DB raises an exception, should return error envelope (never raise)."""
        with patch.object(
            _ss_mod,
            "get_async_session",
            side_effect=Exception("DB connection error"),
        ):
            result = await _invoke("mechas")

        assert "error" in result or result.get("count", 0) == 0


# ---------------------------------------------------------------------------
# REQ-1 / REQ-2: Metadata-first filtering and no-silent-fallback
# ---------------------------------------------------------------------------


async def _invoke_with_audience(query: str, audience: str, services: list) -> dict:
    """Helper to call search_services with audience param."""
    args: dict[str, Any] = {"query": query, "audience": audience, "max_results": 10}
    with _patch_db(services):
        return await _ss_mod.search_services.ainvoke(args)


# Fixtures for REQ-1 tests — use services with disambiguation_tags for proper scoring
CORTE_FEMALE = _make_service(
    "Cortar",
    duration_minutes=40,
    description="Corte capilar dama",
    metadata_={
        "family": "haircut",
        "audience": "adult_female",
        "disambiguation_tags": ["cortar", "corte", "corte dama", "corte mujer"],
        "ask_if_missing": [],
    },
)

CORTE_MALE = _make_service(
    "Corte Caballero",
    duration_minutes=30,
    metadata_={
        "family": "haircut",
        "audience": "adult_male",
        "disambiguation_tags": ["corte caballero", "caballero"],
        "ask_if_missing": [],
    },
)

CORTE_BABY = _make_service(
    "Corte Bebé",
    duration_minutes=20,
    metadata_={
        "family": "haircut",
        "audience": "baby",
        "disambiguation_tags": ["corte bebe", "bebe"],
        "ask_if_missing": [],
    },
)

CORTE_MALE = _make_service(
    "Corte Caballero",
    duration_minutes=30,
    metadata_={
        "family": "haircut",
        "audience": "adult_male",
        "disambiguation_tags": [],
        "ask_if_missing": [],
    },
)

CORTE_BABY = _make_service(
    "Corte Bebé",
    duration_minutes=20,
    metadata_={
        "family": "haircut",
        "audience": "baby",
        "disambiguation_tags": [],
        "ask_if_missing": [],
    },
)

# A service with null/absent metadata_.audience — keyword fallback applies
TINTE_NO_META_AUDIENCE = _make_service(
    "Tinte caballero color",
    duration_minutes=90,
    metadata_={
        "family": "color",
        "audience": None,
        "disambiguation_tags": ["caballero"],
        "ask_if_missing": [],
    },
)


@pytest.mark.asyncio
class TestMatchesAudienceMetadataFirst:
    """REQ-1: _matches_audience uses metadata_.audience as primary signal."""

    async def test_search_female_audience_excludes_male_and_baby(self):
        """REQ-1 Scenario: search 'corte' with audience='adult_female' returns only Cortar."""
        result = await _invoke_with_audience(
            "corte", "adult_female", [CORTE_FEMALE, CORTE_MALE, CORTE_BABY]
        )
        # Should contain only Cortar (adult_female)
        service_names = []
        if "resolved_service" in result:
            service_names = [result["resolved_service"]["name"]]
        elif "services" in result:
            service_names = [s["name"] for s in result["services"]]
        elif "clarification_needed" in result:
            service_names = [o["service_name"] for o in result["clarification_needed"]["options"]]

        assert "Cortar" in service_names, f"Expected 'Cortar' in {service_names}"
        assert "Corte Caballero" not in service_names, f"Male service leaked: {service_names}"
        assert "Corte Bebé" not in service_names, f"Baby service leaked: {service_names}"

    async def test_search_male_audience_excludes_female_and_baby(self):
        """REQ-1: male audience filter returns only adult_male services."""
        result = await _invoke_with_audience(
            "corte", "adult_male", [CORTE_FEMALE, CORTE_MALE, CORTE_BABY]
        )
        service_names = []
        if "resolved_service" in result:
            service_names = [result["resolved_service"]["name"]]
        elif "services" in result:
            service_names = [s["name"] for s in result["services"]]
        elif "clarification_needed" in result:
            service_names = [o["service_name"] for o in result["clarification_needed"]["options"]]

        assert "Corte Caballero" in service_names, f"Expected male service in {service_names}"
        assert "Cortar" not in service_names, f"Female service leaked: {service_names}"


class TestMatchesAudienceUnit:
    """Unit tests for _matches_audience() — synchronous function."""

    def test_metadata_audience_match_returns_true(self):
        """Service with metadata_.audience == audience → True, no keyword scan."""
        result = _ss_mod._matches_audience(CORTE_FEMALE, "adult_female")
        assert result is True

    def test_metadata_audience_mismatch_returns_false(self):
        """Service with metadata_.audience != audience → False, no keyword scan."""
        result = _ss_mod._matches_audience(CORTE_MALE, "adult_female")
        assert result is False

    def test_metadata_audience_present_skips_keyword_scan(self):
        """When metadata_.audience is present, keyword scan is never performed.

        CORTE_MALE has name 'Corte Caballero' which would match the 'caballero' keyword
        for adult_male. But since metadata_.audience = 'adult_male', matching 'adult_female'
        must return False without any keyword lookup.
        """
        # CORTE_MALE name contains 'Caballero' (adult_male keyword) — but we ask for adult_female
        result = _ss_mod._matches_audience(CORTE_MALE, "adult_female")
        assert result is False

    def test_metadata_audience_null_with_family_is_unisex(self):
        """Service with family + audience=None is intentionally unisex — always matches."""
        # TINTE_NO_META_AUDIENCE has family="color" and audience=None → unisex service
        result_male = _ss_mod._matches_audience(TINTE_NO_META_AUDIENCE, "adult_male")
        result_female = _ss_mod._matches_audience(TINTE_NO_META_AUDIENCE, "adult_female")
        assert result_male is True
        assert result_female is True

    def test_unisex_service_matches_any_audience(self):
        """Unisex service (has family, audience=None) always matches any audience."""
        svc = MagicMock()
        svc.metadata_ = {"family": "hairstyle", "audience": None}
        svc.name = "Peinado"
        svc.description = "Peinado profesional"
        assert _ss_mod._matches_audience(svc, "adult_female") is True
        assert _ss_mod._matches_audience(svc, "adult_male") is True
        assert _ss_mod._matches_audience(svc, "baby") is True

    def test_service_with_family_and_audience_exact_match(self):
        """Service with family + explicit audience → exact match only."""
        svc = MagicMock()
        svc.metadata_ = {"family": "haircut", "audience": "adult_male"}
        svc.name = "Corte Caballero"
        svc.description = "Corte para caballero"
        assert _ss_mod._matches_audience(svc, "adult_male") is True
        assert _ss_mod._matches_audience(svc, "adult_female") is False

    def test_no_metadata_falls_back_to_keywords(self):
        """Service with no family metadata → keyword fallback only."""
        svc = MagicMock()
        svc.metadata_ = {}
        svc.name = "Manicura Caballero"
        svc.description = "Manicura para caballero"
        assert _ss_mod._matches_audience(svc, "adult_male") is True
        assert _ss_mod._matches_audience(svc, "adult_female") is False

    def test_metadata_absent_falls_back_to_keywords(self):
        """Service with no metadata at all falls back to keyword matching."""
        svc = _make_service("Corte Caballero Barbería", metadata_={})
        # No metadata_.audience key at all — should use keyword fallback
        result = _ss_mod._matches_audience(svc, "adult_male")
        assert result is True


@pytest.mark.asyncio
class TestNoSilentFallback:
    """REQ-2: audience filter that eliminates all results returns [] + WARNING log."""

    async def test_empty_result_when_no_audience_match(self, caplog):
        """When audience filter eliminates all results, return empty list + WARNING."""
        import logging

        # All services are adult_female — no adult_male services exist
        with caplog.at_level(logging.WARNING, logger="agent.tools.search_services"):
            result = await _invoke_with_audience("corte", "adult_male", [CORTE_FEMALE])

        # Must return empty (not silently fall back to CORTE_FEMALE)
        count = result.get("count", -1)
        assert count == 0, f"Expected count=0 but got {count}. Result: {result}"

        if "services" in result:
            assert (
                result["services"] == []
            ), f"Expected empty services list but got {result['services']}"

        # WARNING log must be emitted
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "adult_male" in msg or "Audience filter" in msg for msg in warning_msgs
        ), f"Expected WARNING about audience filter. Got: {warning_msgs}"

    async def test_no_fallback_does_not_leak_wrong_gender(self):
        """Regression: female-only catalog must NOT return male results when male audience requested."""
        result = await _invoke_with_audience("corte", "adult_male", [CORTE_FEMALE, CORTE_BABY])
        # Neither CORTE_FEMALE nor CORTE_BABY should appear
        service_names = []
        if "resolved_service" in result:
            service_names = [result["resolved_service"]["name"]]
        elif "services" in result:
            service_names = [s["name"] for s in result["services"]]

        assert "Cortar" not in service_names, f"Female service leaked: {service_names}"
        assert "Corte Bebé" not in service_names, f"Baby service leaked: {service_names}"

    async def test_none_audience_applies_no_filter(self):
        """REQ-2 Scenario: audience=None → no filter, all matching services returned."""
        with _patch_db([CORTE_FEMALE, CORTE_MALE, CORTE_BABY]):
            result = await _ss_mod.search_services.ainvoke({"query": "corte", "max_results": 10})

        # All 3 services should potentially appear (no audience filter)
        services = result.get("services", [])
        resolved = result.get("resolved_service")
        clarification = result.get("clarification_needed")

        total = (
            (1 if resolved else 0)
            + (len(services))
            + (len(clarification["options"]) if clarification else 0)
        )
        assert total > 0, f"Expected some services when audience=None, got: {result}"
