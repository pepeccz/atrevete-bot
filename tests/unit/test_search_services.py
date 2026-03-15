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

import importlib.util
import sys
import uuid
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
    # Stub langchain_core before loading
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

        assert "clarification_needed" in result, (
            f"Expected 'clarification_needed' key in result, got: {list(result.keys())}"
        )
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

        assert "resolved_service" in result, (
            f"Expected 'resolved_service' key in result, got: {list(result.keys())}"
        )
        resolved = result["resolved_service"]
        assert resolved["name"] == "Corte Caballero"
        assert resolved["duration_minutes"] == 40
        assert "id" in resolved
        assert result["count"] == 1

    async def test_resolved_service_has_id_field(self):
        """resolved_service envelope must include id (restored in v3.2)."""
        with _patch_db([CORTE_CABALLERO]):
            result = await _invoke("corte caballero")

        resolved = result["resolved_service"]
        assert "id" in resolved
        assert resolved["id"] == str(CORTE_CABALLERO.id)

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

        assert "services" in result, (
            f"Expected 'services' key in result, got: {list(result.keys())}"
        )
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
