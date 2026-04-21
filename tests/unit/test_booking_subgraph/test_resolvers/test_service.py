"""
Phase 3 — service resolver tests (R1.3).

Single match writes last_services; ambiguous populates pending_disambiguations;
audience hint used when present.

Phase 2 (catalog-loader SDD) — resolver accepts list[ServiceRow] AND list[str];
audience filtering is data-driven via Service.audience column.
"""

from __future__ import annotations

import pytest


# Legacy string catalog — preserved for backward-compat tests.
_CATALOG = ["Corte Señora", "Corte Caballero", "Mechas", "Uñas"]


def _row(name: str, audience: str | None = None, metadata: dict | None = None):
    from agent.prompts.catalog_builder import ServiceRow

    return ServiceRow(name=name, audience=audience, metadata=dict(metadata or {}))


# Typed-row catalog — real production shape.
def _row_catalog():
    return [
        _row("Cortar", audience=None),  # neutral
        _row("Corte Caballero", audience="adult_male"),
        _row("Corte Niño", audience="child_male"),
        _row("Corte Niña", audience="child_female"),
        _row("Mechas", audience="adult_female"),
        _row("Uñas", audience="unisex"),
    ]


# ---------------------------------------------------------------------------
# Legacy list[str] path (pre-Phase-2 contract) — MUST still work.
# ---------------------------------------------------------------------------


def test_unambiguous_match_writes_last_services():
    from agent.booking.resolvers.service import resolve

    bc = {"service_audience_hint": "FEMALE"}
    result = resolve("quiero cortarme el pelo", bc, {"service_catalog": _CATALOG})
    assert result is not None and result["matched"]
    assert "Corte Señora" in result["patch"].get("last_services", [])


def test_ambiguous_populates_pending_disambiguations():
    from agent.booking.resolvers.service import resolve

    result = resolve("corte", {}, {"service_catalog": _CATALOG})
    assert result is not None and result["matched"]
    disambig = result["patch"].get("pending_disambiguations") or []
    assert len(disambig) >= 2


def test_no_match_returns_none():
    from agent.booking.resolvers.service import resolve

    result = resolve("quiero pizza", {}, {"service_catalog": _CATALOG})
    assert result is None or not result.get("matched")


def test_female_hint_disambiguates_to_corte_senora():
    from agent.booking.resolvers.service import resolve

    bc = {"service_audience_hint": "FEMALE"}
    result = resolve("corte", bc, {"service_catalog": _CATALOG})
    assert result is not None and result["matched"]
    assert result["patch"].get("last_services") == ["Corte Señora"] or \
           len(result["patch"].get("pending_disambiguations", [])) >= 1


# ---------------------------------------------------------------------------
# Phase 2 — resolver accepts list[ServiceRow] and filters by Service.audience
# ---------------------------------------------------------------------------


def test_resolver_accepts_service_row_catalog():
    """ServiceRow input is the new production shape — must be recognized."""
    from agent.booking.resolvers.service import resolve

    result = resolve("corte", {}, {"service_catalog": _row_catalog()})
    assert result is not None and result["matched"]
    disambig = result["patch"].get("pending_disambiguations") or []
    single = result["patch"].get("last_services") or []
    assert disambig or single, "ServiceRow catalog must produce a match"


@pytest.mark.parametrize(
    "audience,hint,expected_retained",
    [
        ("adult_female", "FEMALE", True),
        ("adult_male", "FEMALE", False),
        ("child_female", "FEMALE", False),
        ("child_male", "FEMALE", False),
        ("unisex", "FEMALE", True),
        (None, "FEMALE", True),
        ("adult_male", "MALE", True),
        ("adult_female", "MALE", False),
        ("unisex", "MALE", True),
        (None, "MALE", True),
        ("child_female", "CHILD", True),
        ("child_male", "CHILD", True),
        ("adult_female", "CHILD", False),
        ("unisex", "CHILD", True),
        (None, "CHILD", False),  # NULL not in CHILD map per spec
    ],
)
def test_audience_column_filter_matrix(audience, hint, expected_retained):
    """_audience_matches reads Service.audience column, not name keywords."""
    from agent.booking.resolvers.service import _audience_matches
    from agent.prompts.catalog_builder import ServiceRow

    row = ServiceRow(name="irrelevant", audience=audience, metadata={})
    assert _audience_matches(row, hint) is expected_retained, (
        f"audience={audience!r} hint={hint!r} expected {expected_retained}"
    )


def test_audience_filter_no_hint_retains_all():
    """No hint → every row retained regardless of audience."""
    from agent.booking.resolvers.service import _audience_matches
    from agent.prompts.catalog_builder import ServiceRow

    for audience in ("adult_female", "adult_male", "child_female", "child_male", "unisex", None):
        row = ServiceRow(name="x", audience=audience, metadata={})
        assert _audience_matches(row, None) is True


# ---------------------------------------------------------------------------
# Phase 3 — loader wiring + opening_booking_request fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_catalog_from_cache_delegates_to_get_active_services(monkeypatch):
    """_load_catalog_from_cache MUST call get_active_services()."""
    from agent.booking.resolvers import service as resolver_mod
    from agent.prompts import catalog_builder

    fake_rows = [_row("Mechas", audience="adult_female")]

    async def fake_get_active_services():
        return fake_rows

    monkeypatch.setattr(catalog_builder, "_catalog_cache", catalog_builder._catalog_cache)
    monkeypatch.setattr(resolver_mod, "get_active_services", fake_get_active_services)

    loaded = await resolver_mod._load_catalog_from_cache_async()
    assert loaded == fake_rows


def test_resolver_uses_loader_when_state_missing_catalog(monkeypatch):
    """When state has no service_catalog, resolver pulls from the cache loader."""
    from agent.booking.resolvers import service as resolver_mod

    catalog = [_row("Mechas", audience="adult_female")]
    monkeypatch.setattr(resolver_mod, "_load_catalog_from_cache", lambda: catalog)

    result = resolver_mod.resolve("mechas", {}, {})
    assert result is not None and result["matched"]
    assert result["patch"].get("last_services") == ["Mechas"]


def test_fallback_fires_when_no_current_match_and_last_services_empty():
    """Second pass over opening_booking_request when current user_text fails."""
    from agent.booking.resolvers import service as resolver_mod

    catalog = _row_catalog()
    # "xyzzy plop" produces no service match across the row catalog.
    bc_no_fb = {"last_services": []}
    baseline = resolver_mod.resolve("xyzzy plop", bc_no_fb, {"service_catalog": catalog})
    assert baseline is None or not baseline.get("matched"), (
        "sanity: 'ok dale' must not match any service directly"
    )

    bc = {
        "opening_booking_request": "quiero cortarme el pelo",
        "last_services": [],
    }
    result = resolver_mod.resolve("xyzzy plop", bc, {"service_catalog": catalog})
    assert result is not None and result["matched"], "fallback must produce a match"
    hit_names = [d["service_name"] for d in result["patch"].get("pending_disambiguations", [])]
    hit_names += result["patch"].get("last_services", [])
    assert any("Corte" in n or "Cortar" in n for n in hit_names)


def test_fallback_skipped_when_last_services_already_populated(monkeypatch):
    """If a service was previously resolved, fallback MUST NOT run."""
    from agent.booking.resolvers import service as resolver_mod

    catalog = _row_catalog()
    bc = {
        "opening_booking_request": "quiero cortarme el pelo",
        "last_services": ["Mechas"],
    }
    # user_text "xyz" no match; fallback disabled → returns None
    result = resolver_mod.resolve("xyz no existe", bc, {"service_catalog": catalog})
    assert result is None or not result.get("matched")


def test_fallback_skipped_when_opening_request_absent(monkeypatch):
    """No opening request → no fallback possible → returns None on no match."""
    from agent.booking.resolvers import service as resolver_mod

    catalog = _row_catalog()
    result = resolver_mod.resolve("xyz no existe", {}, {"service_catalog": catalog})
    assert result is None or not result.get("matched")


def test_female_hint_excludes_male_row():
    """FEMALE hint with row catalog drops adult_male services."""
    from agent.booking.resolvers.service import resolve

    bc = {"service_audience_hint": "FEMALE"}
    result = resolve("corte", bc, {"service_catalog": _row_catalog()})
    assert result is not None
    disambig = result["patch"].get("pending_disambiguations") or []
    single = result["patch"].get("last_services") or []
    hit_names = [d["service_name"] for d in disambig] + single
    assert "Corte Caballero" not in hit_names
    assert "Corte Niño" not in hit_names
