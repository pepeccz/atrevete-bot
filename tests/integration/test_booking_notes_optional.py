"""
Integration tests for the notes-optional gate change (R8, S8).

C4.1: Verify that _build_response does NOT include "notas" in missing.
      _booking_complete must return True when selected_slot + customer_name set.
      The `book` tool must be present in get_tools when booking is complete.

TDD cycle:
- Must FAIL before C4.2 (current _build_response still appends "notas" to missing).
- Must PASS after C4.2.

Covers: R8, S8.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.modes.booking_mode import BookingModeNode


# ---------------------------------------------------------------------------
# Node factory — minimal, no async I/O needed for these tests
# ---------------------------------------------------------------------------


def _make_node() -> BookingModeNode:
    with patch("agent.modes.booking_mode.BaseModeNode.__init__", return_value=None):
        node = BookingModeNode.__new__(BookingModeNode)
    return node


# ---------------------------------------------------------------------------
# C4.1 — Notes optional at gate level
# ---------------------------------------------------------------------------


class TestNotesOptionalGate:
    """
    R8/S8: _build_response must NOT include 'notas' in missing.
    _booking_complete must return True when slot + name are set (no notes gate).
    """

    def test_build_response_does_not_include_notas_in_missing(self) -> None:
        """R8: _build_response must NOT append 'notas' to missing array.

        FAILS on master because lines 201-205 of booking_data_tools.py
        unconditionally append 'notas' when notes_asked is False.
        """
        from agent.tools.booking_data_tools import _build_response

        # All required fields set, notes_asked=False (default), notes=None
        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "add_more_asked": True,
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana García",
            # notes_asked NOT set — should NOT block completion
        }

        result = _build_response(ctx, success=True)

        assert "notas" not in result["missing"], (
            f"'notas' must NOT appear in missing after R8 fix. "
            f"Got missing={result['missing']!r}. "
            "FAILS on master because _build_response still appends 'notas' to missing."
        )

    def test_build_response_next_step_not_blocked_by_notas(self) -> None:
        """R8: next_step must NOT be 'Falta: notas' when all other fields are set.

        FAILS on master: with notas in missing, next_step='Falta: notas' and
        the LLM reads it as a mandatory pending step — creating a deadlock.
        """
        from agent.tools.booking_data_tools import _build_response

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "add_more_asked": True,
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana García",
        }

        result = _build_response(ctx, success=True)

        assert result["next_step"] != "Falta: notas", (
            f"next_step must not be 'Falta: notas'. Got: {result['next_step']!r}. "
            "FAILS on master because notas is in missing and blocks next_step."
        )
        # The correct next_step when all required data is collected:
        assert "recogidos" in result["next_step"] or "confirmación" in result["next_step"], (
            f"When all required fields are collected, next_step should indicate completion. "
            f"Got: {result['next_step']!r}"
        )

    def test_booking_complete_returns_true_without_notes(self) -> None:
        """S8: _booking_complete must return True when slot + name are set, no notes.

        This gate is already correct on master (booking_mode.py:104-125 does not gate
        on notes_asked). This test confirms no regression.
        """
        node = _make_node()

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "add_more_asked": True,
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana García",
            # notes_asked NOT set
        }

        is_complete, missing = node._booking_complete(ctx)

        assert is_complete is True, (
            f"_booking_complete must return True when slot + name are set "
            f"(notes are optional). Got is_complete={is_complete}, missing={missing}"
        )
        assert "notas" not in missing, (
            f"_booking_complete must NOT list 'notas' in missing. Got missing={missing}"
        )

    def test_book_tool_present_when_complete_without_notes(self) -> None:
        """S8: `book` tool must be available in get_tools when booking is complete without notes."""
        node = _make_node()

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "add_more_asked": True,
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana García",
            # notes_asked NOT set — booking should still be complete
        }

        tools = node.get_tools(ctx)
        tool_names = [t.name if hasattr(t, "name") else str(t) for t in tools]

        assert "book" in tool_names, (
            f"'book' tool must be present when all required fields are set (notes optional). "
            f"Got tools: {tool_names}"
        )

    def test_notes_in_collected_when_notes_asked_set(self) -> None:
        """When notes_asked=True, notes info should still appear in collected (not missing)."""
        from agent.tools.booking_data_tools import _build_response

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "add_more_asked": True,
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana García",
            "notes_asked": True,
            "notes": "Tiene alergia al amoniaco",
        }

        result = _build_response(ctx, success=True)

        # Notes info should be in collected, not missing
        collected_str = " ".join(result["collected"])
        assert "notas" in collected_str.lower() or "alergia" in collected_str.lower(), (
            f"When notes_asked=True and notes are set, notes info should appear in collected. "
            f"Got collected={result['collected']!r}"
        )
        assert "notas" not in result["missing"], (
            f"'notas' must never be in missing. Got missing={result['missing']!r}"
        )


# ---------------------------------------------------------------------------
# C5.1 — flow_hint must NOT show "notas" as pending (W1 follow-up)
# ---------------------------------------------------------------------------


class TestFlowHintNotasLeak:
    """
    W1: _build_flow_hint must NOT include "notas" in pending when notes_asked=False.

    Before C5.2 fix, _build_flow_hint always appends "notas" to pending when
    notes_asked is falsy — even though notes are optional at the gate level (R8).
    This causes <flow_hint>Pendiente: notas</flow_hint> on every turn, creating
    LLM behavioral pressure to ask for notes before calling `book`.

    TDD cycle:
    - FAILS before C5.2 (else: pending.append("notas") still present).
    - PASSES after C5.2 (that branch is removed).
    """

    @pytest.mark.xfail(
        reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
        strict=True,
    )
    def test_flow_hint_no_notas_pending_when_complete_without_notes(self) -> None:
        """W1/R8: _build_flow_hint must NOT show 'notas' as pending when booking is complete.

        Given all required fields (services, stylist, slot, name) and notes_asked=False,
        the flow hint must not contain 'Pendiente: notas' or 'notas' in the pending list.
        FAILS on master: line 215 of booking_mode.py unconditionally appends "notas" to pending
        when notes_asked is falsy.
        """
        node = _make_node()

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "add_more_asked": True,
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana García",
            # notes_asked NOT set — notes are optional
        }

        hint = node._build_flow_hint(ctx)

        assert "Pendiente: notas" not in hint, (
            f"_build_flow_hint must NOT show 'Pendiente: notas' when booking is complete "
            f"and notes are optional. Got: {hint!r}. "
            "FAILS on master because of the else: pending.append('notas') branch."
        )
        # Verify "notas" does not appear anywhere in the pending segment
        # (could be combined like "Pendiente: nombre, notas")
        if "Pendiente:" in hint:
            pending_segment = hint.split("Pendiente:")[1].split("</flow_hint>")[0]
            assert "notas" not in pending_segment, (
                f"'notas' must not appear in the Pendiente segment of flow_hint. "
                f"Got pending segment: {pending_segment!r}"
            )

    @pytest.mark.xfail(
        reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
        strict=True,
    )
    def test_confirmation_shown_set_when_complete_without_notes(self) -> None:
        """W1: _confirmation_shown must be set to True when all required fields collected.

        With the leak present, pending is never empty (always has "notas"), so
        _confirmation_shown is never set, and the hint never reaches
        "Todos los datos recogidos".
        FAILS on master for the same reason as above.
        """
        node = _make_node()

        ctx: dict = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "add_more_asked": True,
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana García",
            # notes_asked NOT set
        }

        node._build_flow_hint(ctx)

        assert ctx.get("_confirmation_shown") is True, (
            f"_confirmation_shown must be True after _build_flow_hint when all required "
            f"fields are set and notes are optional. Got: {ctx.get('_confirmation_shown')!r}. "
            "FAILS on master because 'notas' is always in pending, blocking the gate."
        )

    @pytest.mark.xfail(
        reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
        strict=True,
    )
    def test_flow_hint_notas_in_collected_when_notes_asked_true(self) -> None:
        """When notes_asked=True, notas should appear in collected (not pending) — no regression."""
        node = _make_node()

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "add_more_asked": True,
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana García",
            "notes_asked": True,
            "notes": "Tiene alergia al amoniaco",
        }

        hint = node._build_flow_hint(ctx)

        assert "notas" in hint, (
            f"When notes_asked=True, notas info must appear somewhere in the hint. Got: {hint!r}"
        )
        assert "Recogido:" in hint and "notas" in hint.split("Recogido:")[1].split("Pendiente:")[0] if "Pendiente:" in hint else "notas" in hint.split("Recogido:")[1], (
            f"When notes_asked=True, notas must be in the Recogido segment. Got: {hint!r}"
        )
