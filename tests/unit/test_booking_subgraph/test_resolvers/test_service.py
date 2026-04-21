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
