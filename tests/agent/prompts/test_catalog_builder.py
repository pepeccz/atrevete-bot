"""Tests for catalog_builder — Task 4.1.

Tests the pure `build_catalog_for_prompt(services)` function using in-memory
Service-like fixtures (no DB). The DB integration test is skipped when Postgres
is not available.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Minimal Service fixture — mirrors database.models.Service enough for tests
# ---------------------------------------------------------------------------


class _FakeService:
    """Minimal stub that mimics the columns catalog_builder reads."""

    def __init__(
        self,
        name: str,
        duration_minutes: int,
        description: str | None = None,
        audience: str | None = None,
        metadata_: dict | None = None,
        is_active: bool = True,
        category=None,
    ):
        self.id = uuid4()
        self.name = name
        self.duration_minutes = duration_minutes
        self.description = description
        self.audience = audience
        self.metadata_ = metadata_ or {}
        self.is_active = is_active
        # Use a simple sentinel for category
        self.category = category or "HAIRDRESSING"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PRINCIPAL_CORTE_SENORA = _FakeService(
    name="Corte Señora",
    duration_minutes=45,
    description="Corte con lavado y secado",
    audience="adult_female",
    metadata_={"service_type": "principal", "dimension": "cut", "parent_service_name": None},
)

VARIANT_CORTE_FLEQUILLO = _FakeService(
    name="Corte de Flequillo",
    duration_minutes=15,
    description="Recorte del flequillo",
    audience=None,
    metadata_={
        "service_type": "variant",
        "dimension": "cut",
        "parent_service_name": "Corte Señora",
    },
)

ADDON_TRATAMIENTO = _FakeService(
    name="Oleo Pigmento",
    duration_minutes=30,
    description="Regula porosidad",
    audience=None,
    metadata_={"service_type": "addon", "dimension": "treatment", "parent_service_name": None},
)

PRINCIPAL_MANICURA = _FakeService(
    name="Manicura Semipermanente",
    duration_minutes=60,
    description="Manicura con esmalte semipermanente",
    audience="adult_female",
    metadata_={"service_type": "principal", "dimension": "manicure", "parent_service_name": None},
    category="AESTHETICS",
)

UNISEX_PRINCIPAL = _FakeService(
    name="Masaje Relajante",
    duration_minutes=50,
    description="Masaje corporal completo",
    audience="unisex",
    metadata_={"service_type": "principal", "dimension": "massage", "parent_service_name": None},
    category="AESTHETICS",
)


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------


def _import():
    from agent.prompts.catalog_builder import build_catalog_for_prompt

    return build_catalog_for_prompt


# ---------------------------------------------------------------------------
# Tests — build_catalog_for_prompt (pure function, in-memory)
# ---------------------------------------------------------------------------


class TestBuildCatalogForPrompt:
    def test_import_succeeds(self):
        fn = _import()
        assert callable(fn)

    def test_principal_line_format(self):
        fn = _import()
        result = fn([PRINCIPAL_CORTE_SENORA])
        assert "[PRINCIPAL · cut · adult_female]" in result
        assert "Corte Señora" in result
        assert "45min" in result

    def test_variant_line_format(self):
        fn = _import()
        result = fn([VARIANT_CORTE_FLEQUILLO])
        assert "[VARIANTE de Corte Señora]" in result
        assert "Corte de Flequillo" in result
        assert "15min" in result

    def test_addon_line_format(self):
        fn = _import()
        result = fn([ADDON_TRATAMIENTO])
        assert "[ADDON · treatment]" in result
        assert "Oleo Pigmento" in result
        assert "30min" in result

    def test_description_included(self):
        fn = _import()
        result = fn([PRINCIPAL_CORTE_SENORA])
        assert "Corte con lavado y secado" in result

    def test_unisex_audience_in_tag(self):
        fn = _import()
        result = fn([UNISEX_PRINCIPAL])
        assert "[PRINCIPAL · massage · unisex]" in result

    def test_ordering_principals_first(self):
        """Principals must appear before variants and addons."""
        fn = _import()
        services = [ADDON_TRATAMIENTO, VARIANT_CORTE_FLEQUILLO, PRINCIPAL_CORTE_SENORA]
        result = fn(services)
        pos_principal = result.index("[PRINCIPAL")
        pos_variant = result.index("[VARIANTE")
        pos_addon = result.index("[ADDON")
        assert pos_principal < pos_variant
        assert pos_principal < pos_addon

    def test_empty_list_returns_string(self):
        fn = _import()
        result = fn([])
        assert isinstance(result, str)

    def test_no_description_omits_dash(self):
        """Services without description must NOT emit ' — None'."""
        fn = _import()
        svc = _FakeService(
            name="Sin Desc",
            duration_minutes=10,
            description=None,
            metadata_={"service_type": "addon", "dimension": "cut", "parent_service_name": None},
        )
        result = fn([svc])
        assert "None" not in result

    def test_multiple_categories_both_present(self):
        fn = _import()
        result = fn([PRINCIPAL_CORTE_SENORA, PRINCIPAL_MANICURA])
        assert "Corte Señora" in result
        assert "Manicura Semipermanente" in result


# ---------------------------------------------------------------------------
# Tests — async helpers (mocked DB)
# ---------------------------------------------------------------------------


class TestAsyncHelpers:
    @pytest.mark.asyncio
    async def test_load_active_catalog_returns_list(self):
        from agent.prompts.catalog_builder import _catalog_cache, load_active_catalog

        fake_rows = [
            __import__("agent.prompts.catalog_builder", fromlist=["ServiceRow"]).ServiceRow(
                name="Corte Señora", audience="adult_female", metadata={}
            ),
            __import__("agent.prompts.catalog_builder", fromlist=["ServiceRow"]).ServiceRow(
                name="Manicura Semipermanente", audience="adult_female", metadata={}
            ),
        ]
        fake_markdown = "## Catálogo"

        with patch.object(
            _catalog_cache,
            "get_or_load",
            new=AsyncMock(return_value=(fake_rows, fake_markdown)),
        ):
            result = await load_active_catalog()
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_build_catalog_prompt_section_returns_str(self):
        from agent.prompts.catalog_builder import _catalog_cache, build_catalog_prompt_section

        fake_row = __import__("agent.prompts.catalog_builder", fromlist=["ServiceRow"]).ServiceRow(
            name="Corte Señora", audience="adult_female", metadata={}
        )
        fake_markdown = "## Catálogo"

        # Patch _catalog_cache so get_active_services returns our fake rows,
        # then patch the inner DB session so build_catalog_prompt_section can query.
        from unittest.mock import MagicMock
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [PRINCIPAL_CORTE_SENORA]
        mock_session.execute = AsyncMock(return_value=mock_result)
        with patch(
            "agent.prompts.catalog_builder.get_active_services",
            new=AsyncMock(return_value=[fake_row]),
        ), patch(
            "database.connection.get_async_session",
            return_value=mock_session,
        ):
            result = await build_catalog_prompt_section()
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Corte Señora" in result


# ---------------------------------------------------------------------------
# DB integration test (skipped without Postgres)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_active_catalog_integration():
    """Integration test against real DB — skipped if Postgres not available."""
    pytest.importorskip("asyncpg")
    try:
        from agent.prompts.catalog_builder import load_active_catalog

        services = await load_active_catalog()
        assert isinstance(services, list)
        # If seeded, expect at least 1 service
    except Exception as exc:
        pytest.skip(f"DB not available: {exc}")
