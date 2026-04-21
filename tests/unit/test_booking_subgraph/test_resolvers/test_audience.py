"""
Phase 3 — audience resolver tests (R1.2).

señora→FEMALE clears pending_disambiguations; caballero→MALE; niño→CHILD;
unrelated text → not matched.
"""

from __future__ import annotations


def test_senora_sets_female():
    from agent.booking.resolvers.audience import resolve

    result = resolve("señora", {}, {})
    assert result is not None and result["matched"]
    assert result["patch"]["service_audience_hint"] == "FEMALE"


def test_caballero_sets_male():
    from agent.booking.resolvers.audience import resolve

    result = resolve("caballero", {}, {})
    assert result is not None and result["matched"]
    assert result["patch"]["service_audience_hint"] == "MALE"


def test_nino_sets_child():
    from agent.booking.resolvers.audience import resolve

    result = resolve("niño", {}, {})
    assert result is not None and result["matched"]
    assert result["patch"]["service_audience_hint"] == "CHILD"


def test_clears_pending_disambiguations():
    from agent.booking.resolvers.audience import resolve

    bc = {"pending_disambiguations": [{"service": "Corte"}]}
    result = resolve("señora", bc, {})
    assert result is not None and result["matched"]
    assert "pending_disambiguations" in (result.get("cleared") or [])


def test_unrelated_text_not_matched():
    from agent.booking.resolvers.audience import resolve

    result = resolve("quiero un corte", {}, {})
    assert result is None or not result.get("matched")


def test_dama_maps_to_female():
    from agent.booking.resolvers.audience import resolve

    result = resolve("para una dama", {}, {})
    assert result is not None and result["matched"]
    assert result["patch"]["service_audience_hint"] == "FEMALE"


def test_user_action_provide_field():
    from agent.booking.resolvers.audience import resolve

    result = resolve("señora", {}, {})
    assert result is not None and result.get("user_action") == "PROVIDE_FIELD"
