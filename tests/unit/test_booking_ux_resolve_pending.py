"""
Tests for BookingModeNode._resolve_pending_selection().

Spec: Task 5.2 — booking-ux-fixes
Scenarios:
  (a) Pick service by number from pending_service_options
  (b) Pick service by exact name
  (c) No pending options → no mutation
  (d) Pick stylist by number from pending_stylist_options
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
# (a) Pick service by number
# ──────────────────────────────────────────────────────────────────────────────


def test_pick_service_by_number(booking_node) -> None:
    """Spec scenario (a): user sends '2' → second service is selected."""
    mode_context: dict = {
        "pending_service_options": ["Mechas", "Mechas balayage", "Mechas babylights"],
    }
    state = _make_state("2")

    booking_node._resolve_pending_selection(state, mode_context)

    assert mode_context["last_services"] == ["Mechas balayage"]
    assert "pending_service_options" not in mode_context


def test_pick_service_by_number_first(booking_node) -> None:
    """Edge case: '1' picks the first option."""
    mode_context: dict = {
        "pending_service_options": ["Mechas", "Mechas balayage", "Mechas babylights"],
    }
    state = _make_state("1")

    booking_node._resolve_pending_selection(state, mode_context)

    assert mode_context["last_services"] == ["Mechas"]
    assert "pending_service_options" not in mode_context


def test_pick_service_by_number_last(booking_node) -> None:
    """Edge case: last valid index picks last option."""
    options = ["Mechas", "Mechas balayage", "Mechas babylights"]
    mode_context: dict = {"pending_service_options": options}
    state = _make_state(str(len(options)))

    booking_node._resolve_pending_selection(state, mode_context)

    assert mode_context["last_services"] == ["Mechas babylights"]
    assert "pending_service_options" not in mode_context


def test_pick_service_by_number_out_of_range(booking_node) -> None:
    """Out-of-range number → no mutation (graceful no-op)."""
    mode_context: dict = {
        "pending_service_options": ["Mechas", "Mechas balayage"],
    }
    state = _make_state("99")

    booking_node._resolve_pending_selection(state, mode_context)

    # Nothing should be set
    assert "last_services" not in mode_context
    assert "pending_service_options" in mode_context  # pending remains unchanged


# ──────────────────────────────────────────────────────────────────────────────
# (b) Pick service by exact name
# ──────────────────────────────────────────────────────────────────────────────


def test_pick_service_by_exact_name(booking_node) -> None:
    """Spec scenario (b): user sends exact service name → matched correctly."""
    mode_context: dict = {
        "pending_service_options": ["Mechas", "Mechas balayage", "Mechas babylights"],
    }
    state = _make_state("Mechas balayage")

    booking_node._resolve_pending_selection(state, mode_context)

    assert mode_context["last_services"] == ["Mechas balayage"]
    assert "pending_service_options" not in mode_context


def test_pick_service_by_name_case_insensitive(booking_node) -> None:
    """Name match is case-insensitive."""
    mode_context: dict = {
        "pending_service_options": ["Mechas balayage"],
    }
    state = _make_state("mechas balayage")

    booking_node._resolve_pending_selection(state, mode_context)

    assert mode_context["last_services"] == ["Mechas balayage"]


# ──────────────────────────────────────────────────────────────────────────────
# (c) No pending options → no mutation
# ──────────────────────────────────────────────────────────────────────────────


def test_no_pending_no_mutation(booking_node) -> None:
    """Spec scenario (c): no pending options → mode_context unchanged."""
    mode_context: dict = {
        "last_services": ["Cortar"],
    }
    state = _make_state("2")

    booking_node._resolve_pending_selection(state, mode_context)

    # last_services must NOT be overwritten
    assert mode_context["last_services"] == ["Cortar"]


def test_empty_user_message_no_mutation(booking_node) -> None:
    """Empty user message → no resolution attempted."""
    mode_context: dict = {
        "pending_service_options": ["Mechas", "Mechas balayage"],
    }
    state = _make_state("")

    booking_node._resolve_pending_selection(state, mode_context)

    # Nothing resolved, pending remains
    assert "last_services" not in mode_context
    assert "pending_service_options" in mode_context


# ──────────────────────────────────────────────────────────────────────────────
# (d) Pick stylist by number
# ──────────────────────────────────────────────────────────────────────────────


def test_pick_stylist_by_number(booking_node) -> None:
    """Spec scenario (d): user sends '5' for stylist → 'Sin preferencia' selected."""
    mode_context: dict = {
        "last_services": ["Mechas"],  # service already resolved
        "pending_stylist_options": ["Ana", "Victor", "Marta", "Pilar", "Sin preferencia"],
    }
    state = _make_state("5")

    booking_node._resolve_pending_selection(state, mode_context)

    assert mode_context["last_stylist"] == "Sin preferencia"
    assert "pending_stylist_options" not in mode_context


def test_pick_stylist_by_name(booking_node) -> None:
    """Stylist picked by name."""
    mode_context: dict = {
        "last_services": ["Cortar"],
        "pending_stylist_options": ["Ana", "Victor", "Marta", "Pilar", "Sin preferencia"],
    }
    state = _make_state("Pilar")

    booking_node._resolve_pending_selection(state, mode_context)

    assert mode_context["last_stylist"] == "Pilar"
    assert "pending_stylist_options" not in mode_context


def test_stylist_not_resolved_when_already_set(booking_node) -> None:
    """If last_stylist is already set, pending_stylist_options is ignored."""
    mode_context: dict = {
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "pending_stylist_options": ["Ana", "Victor"],
    }
    state = _make_state("2")

    booking_node._resolve_pending_selection(state, mode_context)

    # last_stylist must NOT be overwritten
    assert mode_context["last_stylist"] == "Ana"
    # pending_stylist_options should remain (no resolution attempted)
    assert "pending_stylist_options" in mode_context


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
