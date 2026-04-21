"""
Phase 3 — date_hint resolver tests (R1.4).

"el viernes" → date_hint set; no date expression → not matched;
overwrite scenario → user_action=CHANGE_DATE.
"""

from __future__ import annotations

import pytest


def test_el_viernes_sets_date_hint():
    from agent.booking.resolvers.date_hint import resolve

    result = resolve("el viernes", {}, {})
    assert result is not None and result["matched"]
    assert "date_hint" in result["patch"]


def test_no_date_expression_not_matched():
    from agent.booking.resolvers.date_hint import resolve

    result = resolve("quiero un corte", {}, {})
    assert result is None or not result.get("matched")


def test_overwrite_existing_date_gives_change_date_action():
    from agent.booking.resolvers.date_hint import resolve

    bc = {"date_hint": "2026-04-20"}
    result = resolve("mejor el lunes", bc, {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "CHANGE_DATE"


def test_first_date_gives_provide_field_action():
    from agent.booking.resolvers.date_hint import resolve

    result = resolve("el martes", {}, {})
    assert result is not None and result["matched"]
    assert result.get("user_action") == "PROVIDE_FIELD"


def test_manana_parsed():
    from agent.booking.resolvers.date_hint import resolve

    result = resolve("mañana", {}, {})
    assert result is not None and result["matched"]
    assert "date_hint" in result["patch"]
