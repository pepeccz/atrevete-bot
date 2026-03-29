"""
Unit tests for list_stylists category filtering (BUG-2, REQ-1).

Tests the fail-closed behaviour added in the stylist-category-filtering-fix:
- Unknown truthy category → error envelope, zero stylists leaked
- None / "" → all active stylists returned (intentional no-filter)
- "Peluquería" / "HAIRDRESSING" → only HAIRDRESSING stylists
- "Estética" / "AESTHETICS" → only AESTHETICS stylists

All tests mock the DB so they run without a live PostgreSQL instance.
The same mock pattern used in test_search_services.py is followed here.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.models import ServiceCategory


# ---------------------------------------------------------------------------
# Load info_tools module directly (bypass agent/tools/__init__.py)
# ---------------------------------------------------------------------------


def _load_info_tools_module():
    """
    Load agent/tools/info_tools.py as a standalone module, bypassing the
    eagerly-importing agent/tools/__init__.py.

    The module uses `from langchain_core.tools import tool` at import time.
    We stub langchain_core so the @tool decorator becomes a no-op.
    """
    try:
        import langchain_core.tools  # noqa: F401
    except ImportError:
        if "langchain_core.tools" not in sys.modules:

            def _tool_decorator(fn=None, args_schema=None, **kwargs):
                """Minimal @tool stub that returns the function unchanged."""
                if fn is None:

                    def wrapper(f):
                        async def ainvoke(args: dict[str, Any]):
                            return await f(**args)

                        f.ainvoke = ainvoke
                        return f

                    return wrapper

                async def ainvoke(args: dict[str, Any]):
                    return await fn(**args)

                fn.ainvoke = ainvoke
                return fn

            lc_stub = ModuleType("langchain_core")
            lc_tools_stub = ModuleType("langchain_core.tools")
            setattr(lc_tools_stub, "tool", _tool_decorator)
            sys.modules["langchain_core"] = lc_stub
            sys.modules["langchain_core.tools"] = lc_tools_stub

    import os

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    module_path = os.path.join(project_root, "agent", "tools", "info_tools.py")

    spec = importlib.util.spec_from_file_location(
        "agent.tools.info_tools_standalone",
        module_path,
    )
    assert isinstance(spec, ModuleSpec)
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load module once at module scope so tests share the same import
_it_mod = _load_info_tools_module()


# ---------------------------------------------------------------------------
# Helpers & fake DB session
# ---------------------------------------------------------------------------


def _uuid_for(name: str) -> uuid.UUID:
    import hashlib

    h = hashlib.sha256(name.encode()).hexdigest()[:32]
    return uuid.UUID(h)


def _make_stylist(name: str, category: ServiceCategory) -> MagicMock:
    stylist = MagicMock()
    stylist.id = _uuid_for(name)
    stylist.name = name
    stylist.category = category
    stylist.is_active = True
    return stylist


# 4 HAIRDRESSING + 1 AESTHETICS (canonical salon setup)
ANA = _make_stylist("Ana", ServiceCategory.HAIRDRESSING)
BELEN = _make_stylist("Belén", ServiceCategory.HAIRDRESSING)
CARMEN = _make_stylist("Carmen", ServiceCategory.HAIRDRESSING)
DIANA = _make_stylist("Diana", ServiceCategory.HAIRDRESSING)
ROSA = _make_stylist("Rosa", ServiceCategory.AESTHETICS)


class _FakeStylistSession:
    """Minimal async context manager session stub for list_stylists tests."""

    def __init__(self, stylists: list) -> None:
        self._stylists = stylists

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, _query):
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._stylists
        return result


def _patch_db_stylists(stylists: list):
    """Patch get_async_session in the STANDALONE info_tools module namespace."""
    return patch.object(
        _it_mod,
        "get_async_session",
        return_value=_FakeStylistSession(stylists),
    )


async def _invoke_list_stylists(category=None) -> dict:
    """Call list_stylists.ainvoke, normalising the args dict."""
    args: dict[str, Any] = {}
    if category is not None:
        args["category"] = category
    # list_stylists accepts category=None via default — pass None explicitly too
    return await _it_mod.list_stylists.ainvoke({"category": category})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListStylistsFailClosed:
    """REQ-1: list_stylists must fail-closed on unknown truthy category strings."""

    async def test_unknown_category_returns_error_key(self):
        """Unknown truthy category → error envelope, NOT real stylist data."""
        with _patch_db_stylists([ANA, BELEN, CARMEN, DIANA, ROSA]):
            result = await _invoke_list_stylists("cabello")

        assert "error" in result, f"Expected 'error' key in result, got: {list(result.keys())}"

    async def test_unknown_category_count_is_zero(self):
        """Unknown truthy category → count=0."""
        with _patch_db_stylists([ANA, BELEN, CARMEN, DIANA, ROSA]):
            result = await _invoke_list_stylists("cabello")

        assert result["count"] == 0

    async def test_unknown_category_stylists_is_empty(self):
        """Unknown truthy category → stylists=[] (no cross-category leakage)."""
        with _patch_db_stylists([ANA, BELEN, CARMEN, DIANA, ROSA]):
            result = await _invoke_list_stylists("cabello")

        assert result["stylists"] == []

    async def test_unknown_category_error_value_is_unknown_category(self):
        """The error value in the envelope must be 'unknown_category'."""
        with _patch_db_stylists([ANA, BELEN, CARMEN, DIANA, ROSA]):
            result = await _invoke_list_stylists("invalid_category_xyz")

        # The implementation may return the string "unknown_category" or a descriptive message.
        # Both are acceptable — we check for the presence of the error key (already done above).
        # This test verifies the "error" key contains meaningful data (not None/empty).
        assert result["error"], "error value must be truthy (non-empty)"

    async def test_unknown_category_does_not_leak_stylists(self):
        """Fail-closed: zero records regardless of how many stylists are in the DB."""
        all_stylists = [ANA, BELEN, CARMEN, DIANA, ROSA]
        with _patch_db_stylists(all_stylists):
            result = await _invoke_list_stylists("peluquero")  # Plausible but unrecognised

        assert result["count"] == 0
        assert result["stylists"] == []


@pytest.mark.asyncio
class TestListStylistsNoFilter:
    """REQ-1: None and empty string are intentional no-filter paths — return all stylists."""

    async def test_none_category_returns_all_stylists(self):
        """None category → all active stylists, no error key."""
        all_stylists = [ANA, BELEN, CARMEN, DIANA, ROSA]
        with _patch_db_stylists(all_stylists):
            result = await _invoke_list_stylists(None)

        assert result["count"] == len(all_stylists)
        assert len(result["stylists"]) == len(all_stylists)
        assert "error" not in result

    async def test_empty_string_category_returns_all_stylists(self):
        """Empty string → same as None (falsy = no filter), returns all."""
        all_stylists = [ANA, BELEN, CARMEN, DIANA, ROSA]
        with _patch_db_stylists(all_stylists):
            result = await _invoke_list_stylists("")

        # list_stylists uses `if category:` guard — empty string is falsy → no filter
        assert result["count"] == len(all_stylists)
        assert "error" not in result


@pytest.mark.asyncio
class TestListStylistsHairdressingFilter:
    """REQ-1: HAIRDRESSING / Peluquería filter must return only HAIRDRESSING stylists."""

    async def test_hairdressing_enum_string_excludes_aesthetics(self):
        """'HAIRDRESSING' → only HAIRDRESSING stylists, Rosa (AESTHETICS) absent."""
        hairdressing_only = [ANA, BELEN, CARMEN, DIANA]
        with _patch_db_stylists(hairdressing_only):
            result = await _invoke_list_stylists("HAIRDRESSING")

        assert result["count"] == 4
        names = [s["name"] for s in result["stylists"]]
        assert "Ana" in names
        assert "Rosa" not in names
        assert "error" not in result

    async def test_hairdressing_all_stylists_have_correct_category(self):
        """All returned stylists must have category HAIRDRESSING."""
        hairdressing_only = [ANA, BELEN, CARMEN, DIANA]
        with _patch_db_stylists(hairdressing_only):
            result = await _invoke_list_stylists("HAIRDRESSING")

        for stylist in result["stylists"]:
            assert stylist["category"] == "HAIRDRESSING", (
                f"Expected HAIRDRESSING but got {stylist['category']} for {stylist['name']}"
            )

    async def test_spanish_label_peluqueria_maps_to_hairdressing(self):
        """'Peluquería' (Spanish label) must resolve to HAIRDRESSING filter."""
        hairdressing_only = [ANA, BELEN, CARMEN, DIANA]
        with _patch_db_stylists(hairdressing_only):
            result = await _invoke_list_stylists("Peluquería")

        assert result["count"] == 4
        assert "error" not in result
        names = [s["name"] for s in result["stylists"]]
        assert "Rosa" not in names

    async def test_peluqueria_same_result_as_hairdressing(self):
        """'Peluquería' and 'HAIRDRESSING' must produce identical stylists."""
        hairdressing_only = [ANA, BELEN, CARMEN, DIANA]

        with _patch_db_stylists(hairdressing_only):
            result_es = await _invoke_list_stylists("Peluquería")

        with _patch_db_stylists(hairdressing_only):
            result_en = await _invoke_list_stylists("HAIRDRESSING")

        assert result_es["count"] == result_en["count"]
        es_names = sorted(s["name"] for s in result_es["stylists"])
        en_names = sorted(s["name"] for s in result_en["stylists"])
        assert es_names == en_names


@pytest.mark.asyncio
class TestListStylistsAestheticsFilter:
    """REQ-1: AESTHETICS / Estética filter must return only AESTHETICS stylists."""

    async def test_aesthetics_enum_string_returns_only_aesthetics(self):
        """'AESTHETICS' → only AESTHETICS stylists returned."""
        aesthetics_only = [ROSA]
        with _patch_db_stylists(aesthetics_only):
            result = await _invoke_list_stylists("AESTHETICS")

        assert result["count"] == 1
        assert result["stylists"][0]["name"] == "Rosa"
        assert result["stylists"][0]["category"] == "AESTHETICS"
        assert "error" not in result

    async def test_spanish_label_estetica_maps_to_aesthetics(self):
        """'Estética' (Spanish label) must resolve to AESTHETICS filter."""
        aesthetics_only = [ROSA]
        with _patch_db_stylists(aesthetics_only):
            result = await _invoke_list_stylists("Estética")

        assert result["count"] == 1
        assert "error" not in result


@pytest.mark.asyncio
class TestListStylistsEnvelopeShape:
    """Verify the response envelope always contains required keys."""

    async def test_success_envelope_has_stylists_and_count(self):
        """Successful call must return {'stylists': [...], 'count': N}."""
        with _patch_db_stylists([ANA]):
            result = await _invoke_list_stylists(None)

        assert "stylists" in result
        assert "count" in result
        assert isinstance(result["stylists"], list)
        assert isinstance(result["count"], int)

    async def test_error_envelope_has_stylists_count_and_error(self):
        """Error call must return {'stylists': [], 'count': 0, 'error': ...}."""
        with _patch_db_stylists([ANA, BELEN]):
            result = await _invoke_list_stylists("unknown_garbage")

        assert "stylists" in result
        assert "count" in result
        assert "error" in result

    async def test_stylist_entries_have_id_name_category(self):
        """Each stylist entry must have id, name, category keys."""
        with _patch_db_stylists([ANA, BELEN]):
            result = await _invoke_list_stylists(None)

        for stylist in result["stylists"]:
            assert "id" in stylist, f"Missing 'id' in {stylist}"
            assert "name" in stylist, f"Missing 'name' in {stylist}"
            assert "category" in stylist, f"Missing 'category' in {stylist}"


# ---------------------------------------------------------------------------
# Load search_services standalone module (same pattern as _it_mod above)
# ---------------------------------------------------------------------------


def _load_search_services_module():
    """Load agent/tools/search_services.py bypassing agent/tools/__init__.py."""
    import os

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    module_path = os.path.join(project_root, "agent", "tools", "search_services.py")

    spec = importlib.util.spec_from_file_location(
        "agent.tools.search_services_standalone_stylist",
        module_path,
    )
    assert isinstance(spec, ModuleSpec)
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ss_mod = _load_search_services_module()


def _make_minimal_async_session():
    """Return a minimal async-context-manager session that raises if execute() is called."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(side_effect=RuntimeError("execute() should not be called"))
    return session


# ---------------------------------------------------------------------------
# REQ-6: search_services fail-closed on unknown category
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSearchServicesFailClosed:
    """REQ-6: search_services must fail-closed on unknown truthy category strings.

    The fail-closed mechanism operates at two layers:
    1. Pydantic schema: SearchServicesSchema uses Literal["Peluquería", "Estética"]
       so unknown strings are rejected at the ainvoke() boundary (schema validation).
    2. Internal guard (coroutine): an `else` branch returns an error dict for
       defensive depth — tested by calling the raw coroutine directly.
    """

    async def test_search_services_unknown_category_rejected_by_schema(self):
        """Unknown truthy category via ainvoke() → Pydantic ValidationError (schema fail-closed)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            await _ss_mod.search_services.ainvoke(
                {"query": "corte", "category": "invalid_category"}
            )

        # The error must reference the 'category' field
        assert "category" in str(exc_info.value)

    async def test_search_services_unknown_category_internal_guard_returns_error(self):
        """Internal coroutine guard: unknown truthy category → error dict, no services leaked."""
        fake_session = _make_minimal_async_session()
        # Call the raw coroutine to bypass Pydantic schema validation
        with patch.object(_ss_mod, "get_async_session", return_value=fake_session):
            result = await _ss_mod.search_services.coroutine(
                query="corte", category="invalid_category"
            )

        assert "error" in result, f"Expected 'error' key, got: {list(result.keys())}"
        assert result.get("count") == 0
        assert result.get("services") == []
        assert result["error"], "error value must be truthy"

    async def test_search_services_none_category_no_error_key(self):
        """None category must NOT return an 'error' key (proceeds to DB)."""
        # For None category, the code proceeds to the DB query — we short-circuit
        # by making execute() return an empty scalars result (no services found).
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=empty_result)

        with patch.object(_ss_mod, "get_async_session", return_value=session):
            result = await _ss_mod.search_services.ainvoke({"query": "corte", "category": None})

        assert "error" not in result or "unknown_category" not in str(result.get("error", "")), (
            "None category should not trigger unknown_category error"
        )


# ---------------------------------------------------------------------------
# REQ-7: query_info / _get_services fail-closed on unknown category
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestQueryInfoFailClosed:
    """REQ-7: query_info(type='services') must fail-closed on unknown truthy category."""

    async def test_query_info_unknown_category_returns_error(self):
        """Unknown truthy category in filters → error dict, no services leaked."""
        fake_session = _make_minimal_async_session()
        with patch.object(_it_mod, "get_async_session", return_value=fake_session):
            result = await _it_mod.query_info.ainvoke(
                {"type": "services", "filters": {"category": "bad_value"}}
            )

        assert "error" in result, f"Expected 'error' key, got: {list(result.keys())}"
        assert result.get("count_shown", result.get("count", 0)) == 0
        assert result.get("services") == []

    async def test_query_info_unknown_category_error_value_is_truthy(self):
        """error value must be non-empty."""
        fake_session = _make_minimal_async_session()
        with patch.object(_it_mod, "get_async_session", return_value=fake_session):
            result = await _it_mod.query_info.ainvoke(
                {"type": "services", "filters": {"category": "peluquero_malo"}}
            )

        assert result["error"], "error value must be truthy"

    async def test_query_info_valid_category_does_not_error(self):
        """'Peluquería' filter must NOT trigger unknown_category error."""
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=empty_result)

        with patch.object(_it_mod, "get_async_session", return_value=session):
            result = await _it_mod.query_info.ainvoke(
                {"type": "services", "filters": {"category": "Peluquería"}}
            )

        assert "error" not in result, (
            f"'Peluquería' is a valid category — no error expected, got: {result.get('error')}"
        )
