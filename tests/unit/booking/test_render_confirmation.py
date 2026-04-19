"""
Unit tests for render_confirmation_summary — Spanish snapshot test.

TDD pair:
- T1.3 RED: this file (function may not be exported yet)
- T1.4 GREEN: agent/booking/grounding.py (render_confirmation_summary)

Requirements: R3
Scenarios: S6
"""

from __future__ import annotations

import pytest

from agent.booking.grounding import render_confirmation_summary


# ============================================================================
# Full booking context fixture
# ============================================================================


def _full_bc(**overrides: object) -> dict:
    base = {
        "last_services": ["Óleo"],
        "last_stylist": "Pilar",
        "selected_slot": {"date": "2026-04-20", "time": "10:00"},
        "customer_name": "Ana García",
        "notes": None,
    }
    base.update(overrides)
    return base


# ============================================================================
# S6 — snapshot: SHOW_CONFIRMATION context contains rendered summary
# ============================================================================


class TestRenderConfirmationSummary:
    def test_output_contains_service(self) -> None:
        result = render_confirmation_summary(_full_bc())
        assert "Óleo" in result

    def test_output_contains_stylist(self) -> None:
        result = render_confirmation_summary(_full_bc())
        assert "Pilar" in result

    def test_output_contains_date_and_time(self) -> None:
        result = render_confirmation_summary(_full_bc())
        assert "2026-04-20" in result
        assert "10:00" in result

    def test_output_contains_customer_name(self) -> None:
        result = render_confirmation_summary(_full_bc())
        assert "Ana García" in result

    def test_output_contains_confirmation_prompt(self) -> None:
        result = render_confirmation_summary(_full_bc())
        assert "confirm" in result.lower() or "sí" in result.lower()

    def test_output_includes_notes_when_present(self) -> None:
        result = render_confirmation_summary(_full_bc(notes="Sin gluten por favor"))
        assert "Sin gluten por favor" in result

    def test_output_omits_notes_when_none(self) -> None:
        result = render_confirmation_summary(_full_bc(notes=None))
        # Notes line should not appear at all
        assert "Notas:" not in result

    def test_output_is_deterministic(self) -> None:
        """Same input → identical output (snapshot test, R3)."""
        bc = _full_bc()
        first = render_confirmation_summary(bc)
        second = render_confirmation_summary(bc)
        assert first == second

    def test_output_is_string(self) -> None:
        result = render_confirmation_summary(_full_bc())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_multiple_services_joined(self) -> None:
        result = render_confirmation_summary(_full_bc(last_services=["Óleo", "Corte Señora"]))
        assert "Óleo" in result
        assert "Corte Señora" in result

    def test_no_preference_stylist_shown(self) -> None:
        result = render_confirmation_summary(_full_bc(last_stylist="Sin preferencia"))
        assert "Sin preferencia" in result

    def test_empty_bc_does_not_raise(self) -> None:
        """render_confirmation_summary must not crash on partial bc."""
        result = render_confirmation_summary({})
        assert isinstance(result, str)
