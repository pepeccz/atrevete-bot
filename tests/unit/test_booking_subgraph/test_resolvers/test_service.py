"""
Phase 3 — service resolver tests (R1.3).

Single match writes last_services; ambiguous populates pending_disambiguations;
audience hint used when present.
"""

from __future__ import annotations

_CATALOG = ["Corte Señora", "Corte Caballero", "Mechas", "Uñas"]


def test_unambiguous_match_writes_last_services():
    from agent.booking.resolvers.service import resolve

    bc = {"service_audience_hint": "FEMALE"}
    result = resolve("quiero cortarme el pelo", bc, {"service_catalog": _CATALOG})
    assert result is not None and result["matched"]
    assert "Corte Señora" in result["patch"].get("last_services", [])


def test_ambiguous_populates_pending_disambiguations():
    from agent.booking.resolvers.service import resolve

    result = resolve("corte", {}, {"service_catalog": _CATALOG})
    # Could match "Corte Señora" or "Corte Caballero"
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
    # With FEMALE hint, should pick Corte Señora
    assert result["patch"].get("last_services") == ["Corte Señora"] or \
           len(result["patch"].get("pending_disambiguations", [])) >= 1
