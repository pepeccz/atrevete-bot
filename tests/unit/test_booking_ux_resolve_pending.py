"""
Tests for BookingModeNode._resolve_pending_selection().

Covers only the deterministic state-machine transitions handled in Python:
  (e) Slot acceptance: offered_slots + digit/time/ordinal/affirmative → selected_slot
  (notes) Notes skip logic at notes_collection step
  (f) Time-pattern and ordinal slot matching
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def booking_node():
    """Create a bare BookingModeNode (no LLM needed for these unit tests)."""
    from agent.modes.booking_mode import BookingModeNode

    return BookingModeNode(tools=[])


def _make_state(user_message: str) -> dict:
    """Minimal ConversationState-compatible dict for testing.

    Uses messages list (canonical channel) so get_last_user_message() works.
    The old user_message field is cleared by preprocess_node before modes run.
    """
    messages = [{"role": "user", "content": user_message}] if user_message else []
    return {"messages": messages, "user_message": None}


# ──────────────────────────────────────────────────────────────────────────────
# (e) Slot acceptance transition (Task 4.3 — agent-state-architecture-fix)
# ──────────────────────────────────────────────────────────────────────────────


def test_slot_acceptance_affirmative(booking_node) -> None:
    """offered_slots + 'Sí' → selected_slot = offered_slots[0], booking_step = confirmation."""
    state = _make_state("Sí")
    mode_context: dict = {
        "offered_slots": [{"stylist_name": "Pilar", "start_time": "2026-04-14T16:00"}],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context["selected_slot"] == {
        "stylist_name": "Pilar",
        "start_time": "2026-04-14T16:00",
    }
    assert mode_context["booking_step"] == "confirmation"


def test_slot_acceptance_digit(booking_node) -> None:
    """offered_slots + '2' → selected_slot = offered_slots[1]."""
    state = _make_state("2")
    mode_context: dict = {
        "offered_slots": [
            {"stylist_name": "Ana", "start_time": "2026-04-14T10:00"},
            {"stylist_name": "Pilar", "start_time": "2026-04-14T16:00"},
        ],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context["selected_slot"] == {
        "stylist_name": "Pilar",
        "start_time": "2026-04-14T16:00",
    }


def test_slot_no_acceptance_without_offered_slots(booking_node) -> None:
    """No offered_slots + 'Sí' → no selected_slot set."""
    state = _make_state("Sí")
    mode_context: dict = {"last_services": ["Cortar"]}
    booking_node._resolve_pending_selection(state, mode_context)
    assert "selected_slot" not in mode_context


def test_slot_acceptance_sets_last_stylist_from_slot(booking_node) -> None:
    """When last_stylist is not set, slot acceptance sets it from slot.stylist_name."""
    state = _make_state("Sí")
    mode_context: dict = {
        "offered_slots": [{"stylist_name": "Marta", "start_time": "2026-04-15T11:00"}],
        "last_services": ["Peinado"],
        # last_stylist intentionally absent
    }
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context["selected_slot"] == {
        "stylist_name": "Marta",
        "start_time": "2026-04-15T11:00",
    }
    assert mode_context["last_stylist"] == "Marta"


def test_slot_not_overwritten_when_already_selected(booking_node) -> None:
    """If selected_slot already exists, offered_slots + 'Sí' → no overwrite."""
    existing_slot = {"stylist_name": "Ana", "start_time": "2026-04-14T10:00"}
    state = _make_state("Sí")
    mode_context: dict = {
        "offered_slots": [{"stylist_name": "Pilar", "start_time": "2026-04-14T16:00"}],
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "selected_slot": existing_slot,
    }
    booking_node._resolve_pending_selection(state, mode_context)
    # The existing slot must NOT be replaced
    assert mode_context["selected_slot"] == existing_slot


# ===========================================================================
# Notes skip logic (scope-realignment task 7.8)
# ===========================================================================


def test_resolve_pending_selection_skips_notes_on_no(booking_node) -> None:
    """'no' response at notes_collection → notes_asked=True, notes=None."""
    state = _make_state("no")
    mode_context: dict = {
        "booking_step": "notes_collection",
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
        "customer_name": "María",
        "add_more_asked": True,
    }
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context["notes_asked"] is True
    assert mode_context.get("notes") is None


def test_resolve_pending_selection_skips_notes_on_nada(booking_node) -> None:
    """'nada' response at notes_collection → notes_asked=True, notes=None."""
    state = _make_state("nada")
    mode_context: dict = {
        "booking_step": "notes_collection",
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
        "customer_name": "María",
        "add_more_asked": True,
    }
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context["notes_asked"] is True
    assert mode_context.get("notes") is None


def test_resolve_pending_selection_skips_notes_on_ninguna(booking_node) -> None:
    """'ninguna' response at notes_collection → notes_asked=True, notes=None."""
    state = _make_state("ninguna")
    mode_context: dict = {
        "booking_step": "notes_collection",
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
        "customer_name": "María",
    }
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context["notes_asked"] is True
    assert mode_context.get("notes") is None


def test_resolve_pending_selection_notes_skip_only_at_notes_step(booking_node) -> None:
    """'no' at service_selection step → does NOT set notes_asked."""
    state = _make_state("no")
    mode_context: dict = {
        "booking_step": "service_selection",
        "last_services": [],
    }
    booking_node._resolve_pending_selection(state, mode_context)
    # notes_asked should NOT be set when step is not notes_collection
    assert "notes_asked" not in mode_context


# ===========================================================================
# (f) Time-pattern and ordinal slot matching (llm-slot-autonomy)
# ===========================================================================


def test_slot_time_match_a_las_11() -> None:
    """'A las 11 está bien' matches slot with time='11:00'."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = _make_state("A las 11 está bien")
    ctx: dict = {
        "offered_slots": [
            {"time": "09:00", "stylist_name": "Pilar"},
            {"time": "09:40", "stylist_name": "Pilar"},
            {"time": "11:00", "stylist_name": "Pilar"},
        ],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    node._resolve_pending_selection(state, ctx)
    assert ctx["selected_slot"]["time"] == "11:00"


def test_slot_ordinal_la_primera() -> None:
    """'La primera' matches offered_slots[0]."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = _make_state("La primera")
    ctx: dict = {
        "offered_slots": [
            {"time": "09:00", "stylist_name": "Pilar"},
            {"time": "11:00", "stylist_name": "Pilar"},
        ],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    node._resolve_pending_selection(state, ctx)
    assert ctx["selected_slot"]["time"] == "09:00"


def test_slot_time_match_9_40() -> None:
    """'Las 9:40' matches slot with time='09:40'."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = _make_state("Las 9:40")
    ctx: dict = {
        "offered_slots": [
            {"time": "09:00", "stylist_name": "Pilar"},
            {"time": "09:40", "stylist_name": "Pilar"},
        ],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    node._resolve_pending_selection(state, ctx)
    assert ctx["selected_slot"]["time"] == "09:40"


def test_slot_digit_still_works() -> None:
    """Backward compat: bare digit still selects slot."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = _make_state("2")
    ctx: dict = {
        "offered_slots": [
            {"time": "09:00", "stylist_name": "Pilar"},
            {"time": "09:40", "stylist_name": "Pilar"},
        ],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    node._resolve_pending_selection(state, ctx)
    assert ctx["selected_slot"]["time"] == "09:40"


def test_slot_time_no_match_returns_none() -> None:
    """Time token that matches zero slots → no resolution (LLM handles)."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = _make_state("A las 8")
    ctx: dict = {
        "offered_slots": [
            {"time": "09:00", "stylist_name": "Pilar"},
            {"time": "11:00", "stylist_name": "Pilar"},
        ],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    node._resolve_pending_selection(state, ctx)
    assert "selected_slot" not in ctx


def test_slot_affirmative_multiple_slots_no_resolution() -> None:
    """'Sí' with multiple slots → no resolution (per spec: affirmative only for 1 slot)."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = _make_state("Sí")
    ctx: dict = {
        "offered_slots": [
            {"time": "09:00", "stylist_name": "Pilar"},
            {"time": "11:00", "stylist_name": "Pilar"},
            {"time": "11:40", "stylist_name": "Ana"},
        ],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    node._resolve_pending_selection(state, ctx)
    assert "selected_slot" not in ctx


def test_slot_time_match_y_media() -> None:
    """'A las 9 y media' matches slot with time='09:30'."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    state = _make_state("A las 9 y media")
    ctx: dict = {
        "offered_slots": [
            {"time": "09:00", "stylist_name": "Pilar"},
            {"time": "09:30", "stylist_name": "Pilar"},
            {"time": "10:00", "stylist_name": "Pilar"},
        ],
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
    }
    node._resolve_pending_selection(state, ctx)
    assert ctx["selected_slot"]["time"] == "09:30"
