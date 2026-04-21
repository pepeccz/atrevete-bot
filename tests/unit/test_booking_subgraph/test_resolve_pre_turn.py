"""
Phase 2 — resolve_pre_turn tests.

RED-first: these tests define the expected behavior before implementation.

Coverage:
- Date-only input preserves existing audience/last_services (conv_id=5 regression)
- Digit input selects an offered slot
- Affirmation sets confirmed=True (when _confirmation_shown=True)
- Negation sets confirmed=False (when _confirmation_shown=True)
- "cualquiera" sets stylist=ANY_AVAILABLE sentinel
- No-entity input leaves booking_context unchanged
- Guards: already-resolved fields not overwritten
- Customer pre-fill from state
"""

from __future__ import annotations

import pytest

from agent.booking.nodes.resolve_pre_turn import ANY_AVAILABLE, resolve_pre_turn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_state(
    user_message: str = "",
    booking_context: dict | None = None,
    **extra,
) -> dict:
    """Construct a minimal ConversationState-shaped dict for testing."""
    return {
        "user_message": user_message,
        "booking_context": booking_context or {},
        "messages": [],
        **extra,
    }


# ---------------------------------------------------------------------------
# Scenario: date-only input — conv_id=5 regression
# audience and last_services must survive a date change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_date_only_preserves_audience_and_services():
    """
    Conv_id=5: user says a date after audience/service already resolved.
    Only date_hint should be updated; audience and last_services untouched.
    """
    bc = {
        "audience": "señora",
        "last_services": ["Cortar Señora"],
    }
    state = make_state(user_message="El miércoles 29", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc["audience"] == "señora"
    assert updated_bc["last_services"] == ["Cortar Señora"]


# ---------------------------------------------------------------------------
# Scenario: digit input selects offered slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digit_selects_offered_slot():
    """
    User sends "1" when offered_slots is non-empty → selected_slot set to slot[0].
    """
    slot0 = {"stylist_name": "Laura", "start_time": "2026-04-23T10:00:00"}
    slot1 = {"stylist_name": "Ana", "start_time": "2026-04-23T11:00:00"}
    bc = {"offered_slots": [slot0, slot1]}
    state = make_state(user_message="1", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc["selected_slot"] == slot0
    assert updated_bc.get("last_stylist") == "Laura"


@pytest.mark.asyncio
async def test_digit_selects_second_offered_slot():
    """Triangulation: digit=2 selects slot[1]."""
    slot0 = {"stylist_name": "Laura", "start_time": "2026-04-23T10:00:00"}
    slot1 = {"stylist_name": "Ana", "start_time": "2026-04-23T11:00:00"}
    bc = {"offered_slots": [slot0, slot1]}
    state = make_state(user_message="2", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc["selected_slot"] == slot1
    assert updated_bc.get("last_stylist") == "Ana"


@pytest.mark.asyncio
async def test_digit_out_of_range_leaves_slot_unset():
    """Out-of-range digit must not set selected_slot."""
    bc = {"offered_slots": [{"stylist_name": "Laura", "start_time": "2026-04-23T10:00:00"}]}
    state = make_state(user_message="5", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc.get("selected_slot") is None


# ---------------------------------------------------------------------------
# Scenario: affirmation → confirmed=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_affirmation_sets_confirmed_true():
    """'sí' after confirmation shown must set confirmed=True."""
    bc = {"_confirmation_shown": True}
    state = make_state(user_message="sí", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc["confirmed"] is True


@pytest.mark.asyncio
async def test_affirmation_dale_sets_confirmed_true():
    """Triangulation: 'dale' also triggers affirmation."""
    bc = {"_confirmation_shown": True}
    state = make_state(user_message="dale", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc["confirmed"] is True


# ---------------------------------------------------------------------------
# Scenario: negation → confirmed=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_negation_sets_confirmed_false():
    """'no' after confirmation shown must set confirmed=False."""
    bc = {"_confirmation_shown": True}
    state = make_state(user_message="no", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc["confirmed"] is False


@pytest.mark.asyncio
async def test_negation_clears_confirmation_shown():
    """Negation must also clear _confirmation_shown so it can be re-shown."""
    bc = {"_confirmation_shown": True}
    state = make_state(user_message="no", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc.get("_confirmation_shown") is False


# ---------------------------------------------------------------------------
# Scenario: "cualquiera" → stylist=ANY_AVAILABLE sentinel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cualquiera_sets_any_available_sentinel():
    """'cualquiera' must set booking_context.last_stylist to ANY_AVAILABLE."""
    bc = {}
    state = make_state(user_message="cualquiera", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc.get("last_stylist") == ANY_AVAILABLE
    assert updated_bc.get("no_preference_stylist") is True


@pytest.mark.asyncio
async def test_la_primera_con_disponibilidad_sets_sentinel():
    """Triangulation: 'la primera con disponibilidad' also triggers ANY_AVAILABLE."""
    bc = {}
    state = make_state(
        user_message="la primera con disponibilidad", booking_context=bc
    )

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc.get("last_stylist") == ANY_AVAILABLE


# ---------------------------------------------------------------------------
# Scenario: no-entity input → booking_context unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_entity_leaves_context_unchanged():
    """Unrecognizable text must not mutate booking_context."""
    bc = {"audience": "señora", "last_services": ["Cortar Señora"]}
    original_bc = dict(bc)
    state = make_state(user_message="hmm no sé", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    # Key fields must be intact
    assert updated_bc.get("audience") == original_bc["audience"]
    assert updated_bc.get("last_services") == original_bc["last_services"]


# ---------------------------------------------------------------------------
# Scenario: guard — already-resolved slot not overwritten by digit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digit_ignored_when_slot_already_selected():
    """If selected_slot already in booking_context, digit input is ignored."""
    existing_slot = {"stylist_name": "Paula", "start_time": "2026-04-23T09:00:00"}
    offered = [{"stylist_name": "Laura", "start_time": "2026-04-23T10:00:00"}]
    bc = {"selected_slot": existing_slot, "offered_slots": offered}
    state = make_state(user_message="1", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc["selected_slot"] == existing_slot


# ---------------------------------------------------------------------------
# Scenario: guard — confirmed not overwritten when already set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_guard_idempotent():
    """If confirmed already set, re-affirming must NOT overwrite."""
    bc = {"_confirmation_shown": True, "confirmed": True}
    state = make_state(user_message="sí", booking_context=bc)

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    # confirmed stays True; no duplicate set
    assert updated_bc["confirmed"] is True


# ---------------------------------------------------------------------------
# Scenario: customer pre-fill from state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_prefill_from_state():
    """
    When state has customer_first_name but booking_context has no
    _suggested_customer_name, resolve_pre_turn must inject the suggestion.
    """
    bc = {}
    state = make_state(
        user_message="quiero reservar",
        booking_context=bc,
        customer_first_name="Valentina",
        customer_id="abc-123",
    )

    result = await resolve_pre_turn(state)

    updated_bc = result.get("booking_context", bc)
    assert updated_bc.get("_suggested_customer_name") == "Valentina"
    assert updated_bc.get("customer_id") == "abc-123"
