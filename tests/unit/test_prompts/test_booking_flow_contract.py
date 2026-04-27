"""Prompt-text contract tests for booking flow changes.

Tests that booking_flow.md, tools_contract.md, and critical_rules.md contain
the required content per the booking-flow-name-notes-extras-loop spec.

Spec refs: SPEC-7.1→7.5, ADR-3, ADR-6, ADR-7.
All tests are RED before prompt files are updated (T7/T8/T9).
"""
from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).parents[3] / "agent" / "prompts" / "shared"


def _read(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T7 — booking_flow.md
# ---------------------------------------------------------------------------


def test_booking_flow_mentions_extras_loop():
    """booking_flow.md documents the extras loop step (SPEC-7.1)."""
    content = _read("booking_flow.md")
    assert "otro servicio" in content or "agregar" in content or "extras_loop" in content, (
        "booking_flow.md must mention the extras loop (otro servicio / agregar / extras_loop)"
    )


def test_booking_flow_mentions_name_ask():
    """booking_flow.md documents name capture step (SPEC-7.1)."""
    content = _read("booking_flow.md")
    content_lower = content.lower()
    assert "nombre" in content_lower and "apellido" in content_lower, (
        "booking_flow.md must mention 'nombre' and 'apellido'"
    )


def test_booking_flow_mentions_notes_offer():
    """booking_flow.md documents notes offer step (SPEC-7.1)."""
    content = _read("booking_flow.md")
    content_lower = content.lower()
    assert "nota" in content_lower or "tener en cuenta" in content_lower, (
        "booking_flow.md must mention notes offer"
    )


def test_booking_flow_confirmation_has_customer_name():
    """booking_flow.md confirmation template includes customer name placeholder (SPEC-7.2)."""
    content = _read("booking_flow.md")
    assert "nombre_pila" in content or "customer_full_name" in content or "{nombre" in content, (
        "booking_flow.md confirmation template must include customer name placeholder"
    )


def test_booking_flow_confirmation_has_notes_clause():
    """booking_flow.md confirmation template includes notes clause (SPEC-7.2)."""
    content = _read("booking_flow.md")
    assert "nota_clause" in content or "nota:" in content.lower() or "notes" in content, (
        "booking_flow.md confirmation template must include notes clause"
    )


# ---------------------------------------------------------------------------
# T8 — tools_contract.md
# ---------------------------------------------------------------------------


def test_tools_contract_lists_new_update_booking_args():
    """tools_contract.md documents all new update_booking args (SPEC-7.3)."""
    content = _read("tools_contract.md")
    for arg in ("extras_asked", "notes_asked", "no_more_services", "customer_full_name", "notes", "customer_known"):
        assert arg in content, f"tools_contract.md must document update_booking arg '{arg}'"


def test_tools_contract_book_uses_start_iso_not_slot_id():
    """tools_contract.md documents book with start_iso, not slot_id (SPEC-7.3)."""
    content = _read("tools_contract.md")
    assert "start_iso" in content, "tools_contract.md must list 'start_iso' for book"
    assert "slot_id" not in content, "tools_contract.md must NOT reference 'slot_id' (old arg name)"


def test_tools_contract_book_uses_customer_full_name():
    """tools_contract.md documents book with customer_full_name, not customer_name (SPEC-7.3)."""
    content = _read("tools_contract.md")
    assert "customer_full_name" in content, (
        "tools_contract.md must list 'customer_full_name' for book"
    )
    # Old arg name must not appear
    assert "customer_name" not in content or "customer_full_name" in content, (
        "tools_contract.md must use 'customer_full_name' not 'customer_name'"
    )


def test_tools_contract_documents_round_trip_flags():
    """tools_contract.md documents round-trip mandate for extras_asked/notes_asked (ADR-3)."""
    content = _read("tools_contract.md")
    content_lower = content.lower()
    # Must contain language about passing back flags
    assert "round" in content_lower or "devuelve" in content_lower or "siguiente llamada" in content_lower, (
        "tools_contract.md must document the round-trip mandate for extras_asked/notes_asked"
    )


# ---------------------------------------------------------------------------
# T9 — critical_rules.md
# ---------------------------------------------------------------------------


def test_critical_rules_forbids_name_fabrication():
    """critical_rules.md contains rule forbidding name fabrication (SPEC-7.4, ADR-6)."""
    content = _read("critical_rules.md")
    content_lower = content.lower()
    assert (
        ("nunca" in content_lower or "never" in content_lower or "no fabrique" in content_lower)
        and "customer_full_name" in content
    ), "critical_rules.md must forbid fabricating customer_full_name"


def test_critical_rules_uses_customer_slot_when_present():
    """critical_rules.md instructs to use <customer> slot name when present (ADR-6)."""
    content = _read("critical_rules.md")
    assert "Nombre:" in content and "customer_known" in content, (
        "critical_rules.md must reference 'Nombre:' line and 'customer_known' arg"
    )
