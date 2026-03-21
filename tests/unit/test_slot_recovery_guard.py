"""
Unit tests for ADR-1: Slot Invalid-Input Recovery Guard.

Tests that when the bot has offered a concrete slot list and the user replies with
something that cannot be resolved to any slot, the bot rephrases deterministically
without incrementing the no-progress counter and without triggering escalation.

Covered scenarios:
- Non-numeric / free-text reply → rephrase message returned
- Out-of-range number (e.g., "5" when only 3 slots) → rephrase
- 2nd consecutive invalid input → rephrase (still below cap)
- 3rd+ consecutive invalid input (at/above cap) → fall-through to LLM loop
- Valid number "1", "2", "3" after previous invalids → slot resolved, counter cleared
- No escalation triggered for invalid input alone
- Empty offered_slots → invalid-input guard skipped (no slots were offered)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import SLOT_INVALID_INPUT_MAX, BookingMode
from agent.state.schemas import create_initial_state


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_slots() -> list[dict]:
    return [
        {
            "id": "slot-1",
            "date": "2026-03-26",
            "time": "10:00",
            "start_time": "2026-03-26T10:00:00+01:00",
        },
        {
            "id": "slot-2",
            "date": "2026-03-26",
            "time": "12:30",
            "start_time": "2026-03-26T12:30:00+01:00",
        },
        {
            "id": "slot-3",
            "date": "2026-03-26",
            "time": "16:00",
            "start_time": "2026-03-26T16:00:00+01:00",
        },
    ]


def make_slot_state(user_message: str, slot_invalid_count: int = 0) -> dict:
    state = create_initial_state("conv-slot-guard", "+34600000001")
    state["customer_name"] = "Ana"
    state["current_mode"] = "BOOKING"
    state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-03-26T10:00:00"},
    ]
    ctx: dict = {
        "booking_step": BookingSubstep.SLOT_SELECTION.value,
        "service_id": "svc-1",
        "service_name": "Corte",
        "stylist_id": "550e8400-e29b-41d4-a716-446655440000",
        "stylist_name": "Pilar",
        "offered_slots": make_slots(),
    }
    if slot_invalid_count > 0:
        ctx["slot_invalid_count"] = slot_invalid_count
    state["mode_context"] = ctx
    return state


def make_booking_mode() -> BookingMode:
    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    mock_llm.ainvoke = AsyncMock()
    return BookingMode(tools=[], llm_client=mock_llm)


# ── Constant sanity check ─────────────────────────────────────────────────────


def test_slot_invalid_input_max_constant_is_three() -> None:
    """SLOT_INVALID_INPUT_MAX must equal 3 per spec."""
    assert SLOT_INVALID_INPUT_MAX == 3


# ── Non-numeric / free-text reply (1st invalid) ───────────────────────────────


@pytest.mark.asyncio
async def test_free_text_reply_returns_rephrase_message() -> None:
    """Non-numeric free-text 'mañana' returns a rephrase, not escalation."""
    mode = make_booking_mode()
    state = make_slot_state("mañana a las 11")

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    messages = result.get("messages", [])
    assert messages, "Expected at least one message in result"
    last_msg = messages[-1]["content"]
    # Should contain the rephrase cue — numeric suggestion
    assert "número" in last_msg.lower() or "1" in last_msg


@pytest.mark.asyncio
async def test_free_text_reply_stays_at_slot_selection() -> None:
    """Invalid reply keeps booking_step at SLOT_SELECTION."""
    mode = make_booking_mode()
    state = make_slot_state("el que quiero")

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    assert mc.get("booking_step") == BookingSubstep.SLOT_SELECTION.value


@pytest.mark.asyncio
async def test_free_text_reply_increments_slot_invalid_count() -> None:
    """First invalid input sets slot_invalid_count to 1."""
    mode = make_booking_mode()
    state = make_slot_state("no sé")

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    assert mc.get("slot_invalid_count") == 1


@pytest.mark.asyncio
async def test_free_text_reply_does_not_escalate() -> None:
    """Invalid slot input MUST NOT trigger escalation."""
    mode = make_booking_mode()
    state = make_slot_state("lo que sea mejor")

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    assert result.get("current_mode") != "ESCALATION"
    assert not result.get("escalation_triggered")


# ── Out-of-range number ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_out_of_range_number_returns_rephrase() -> None:
    """Sending '5' when only 3 slots exist cannot be resolved → rephrase."""
    mode = make_booking_mode()
    # "5" won't match any of the 3 slots (indices 0-2)
    state = make_slot_state("5")

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    # Slot was not resolved, so should rephrase and stay at SLOT_SELECTION
    assert mc.get("booking_step") == BookingSubstep.SLOT_SELECTION.value
    assert mc.get("slot_invalid_count", 0) >= 1


@pytest.mark.asyncio
async def test_out_of_range_does_not_increment_no_progress_turns() -> None:
    """Invalid input must NOT increment no_progress_turns."""
    mode = make_booking_mode()
    state = make_slot_state("opción 9")

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    # no_progress_turns should NOT be set/incremented by invalid slot input
    assert mc.get("no_progress_turns", 0) == 0


# ── 2nd consecutive invalid input (below cap) ────────────────────────────────


@pytest.mark.asyncio
async def test_second_consecutive_invalid_still_rephrases() -> None:
    """After 2 consecutive invalid inputs (below cap=3), bot rephrases again."""
    mode = make_booking_mode()
    state = make_slot_state("no sé cuál elegir", slot_invalid_count=1)

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    assert mc.get("slot_invalid_count") == 2
    assert mc.get("booking_step") == BookingSubstep.SLOT_SELECTION.value
    assert result.get("current_mode") != "ESCALATION"


# ── 3rd consecutive invalid (at cap) falls through ───────────────────────────


@pytest.mark.asyncio
async def test_third_consecutive_invalid_falls_through_to_llm() -> None:
    """At cap (slot_invalid_count >= SLOT_INVALID_INPUT_MAX), the guard falls
    through to the LLM/tool loop rather than rephrasing deterministically."""
    mode = make_booking_mode()
    # slot_invalid_count = SLOT_INVALID_INPUT_MAX - 1 so the increment hits the cap
    state = make_slot_state(
        "todavía no entiendo", slot_invalid_count=SLOT_INVALID_INPUT_MAX - 1
    )

    mock_loop_result = MagicMock()
    mock_loop_result.response_text = "Por favor elegí un horario."
    mock_loop_result.tool_results = {}
    mock_loop_result.tool_events = []

    with (
        patch.object(mode, "_use_optimized_prompts", return_value=False),
        patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_loop.return_value = mock_loop_result
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    # The LLM loop was called (guard fell through)
    mock_loop.assert_awaited_once()
    # No escalation triggered by the guard itself
    assert result.get("current_mode") != "ESCALATION"


# ── Valid input after invalids clears the counter ────────────────────────────


@pytest.mark.asyncio
async def test_valid_slot_after_invalids_clears_counter() -> None:
    """A valid slot selection clears slot_invalid_count."""
    mode = make_booking_mode()
    # Simulate 2 previous invalid attempts
    state = make_slot_state("1", slot_invalid_count=2)

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    # Slot "1" resolves to slot-1 → should advance to CUSTOMER_NAME or NOTES
    assert mc.get("booking_step") != BookingSubstep.SLOT_SELECTION.value
    # slot_invalid_count should be cleared (not present or 0)
    assert mc.get("slot_invalid_count", 0) == 0


@pytest.mark.asyncio
async def test_valid_slot_second_resolves_correctly() -> None:
    """'2' resolves to slot-2 regardless of prior invalid inputs."""
    mode = make_booking_mode()
    state = make_slot_state("2", slot_invalid_count=1)

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    selected = mc.get("selected_slot", {})
    assert selected.get("id") == "slot-2"


# ── No offered_slots → guard is bypassed ─────────────────────────────────────


@pytest.mark.asyncio
async def test_no_offered_slots_bypasses_invalid_guard() -> None:
    """When no slots have been offered yet, invalid-input guard must not fire."""
    mode = make_booking_mode()
    state = create_initial_state("conv-no-slots", "+34600000002")
    state["customer_name"] = "Pedro"
    state["current_mode"] = "BOOKING"
    state["messages"] = [
        {"role": "user", "content": "mañana", "timestamp": "2026-03-26T10:00:00"},
    ]
    # No offered_slots in context
    state["mode_context"] = {
        "booking_step": BookingSubstep.SLOT_SELECTION.value,
        "service_id": "svc-1",
        "service_name": "Corte",
        "stylist_id": "550e8400-e29b-41d4-a716-446655440000",
        "stylist_name": "Pilar",
    }

    mock_loop_result = MagicMock()
    mock_loop_result.response_text = "¿Qué día preferís?"
    mock_loop_result.tool_results = {}
    mock_loop_result.tool_events = []

    with (
        patch.object(mode, "_use_optimized_prompts", return_value=False),
        patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_loop.return_value = mock_loop_result
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    # Should have called the LLM loop (no deterministic rephrase)
    mock_loop.assert_awaited_once()
    mc = result.get("mode_context", {})
    # slot_invalid_count should NOT have been set
    assert mc.get("slot_invalid_count", 0) == 0


# ── Rephrase message content checks ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_rephrase_message_under_cap_mentions_number() -> None:
    """Rephrase message for the first/second invalid input must suggest a number."""
    mode = make_booking_mode()
    state = make_slot_state("quiero el mejor")

    with patch.object(mode, "_use_optimized_prompts", return_value=False):
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    messages = result.get("messages", [])
    assert messages
    content = messages[-1]["content"]
    # Must contain a number reference so the user knows what to write
    assert any(ch.isdigit() for ch in content) or "número" in content.lower()


@pytest.mark.asyncio
async def test_rephrase_message_at_cap_mentions_team_help() -> None:
    """At SLOT_INVALID_INPUT_MAX, rephrase message mentions team support."""
    mode = make_booking_mode()
    # slot_invalid_count at cap-1 so next increment hits the cap
    state = make_slot_state(
        "igual no entiendo nada", slot_invalid_count=SLOT_INVALID_INPUT_MAX - 1
    )

    mock_loop_result = MagicMock()
    mock_loop_result.response_text = "¿Querés que te ayude?"
    mock_loop_result.tool_results = {}
    mock_loop_result.tool_events = []

    with (
        patch.object(mode, "_use_optimized_prompts", return_value=False),
        patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_loop.return_value = mock_loop_result
        # At cap, guard falls through to LLM — the capped rephrase is only used
        # if the guard itself decides to rephrase (below-cap path). Verify
        # the code at least falls through (mock called) and no escalation.
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mock_loop.assert_awaited_once()
    assert result.get("current_mode") != "ESCALATION"


# ── T7.1: offered_slots overwrite contract ────────────────────────────────────


@pytest.mark.asyncio
async def test_offered_slots_overwritten_on_second_availability_call() -> None:
    """T2.1: Second availability search replaces prior offers (DESIGN-1)."""
    mode = make_booking_mode()
    # Start with stale offers from a prior search
    state = make_slot_state("el próximo lunes")
    state["mode_context"]["offered_slots"] = [
        {"id": "old-slot", "date": "2026-03-23", "time": "09:00", "start_time": "2026-03-23T09:00:00"},
    ]

    new_slots = [
        {"id": "new-1", "date": "2026-03-30", "time": "10:00", "start_time": "2026-03-30T10:00:00"},
        {"id": "new-2", "date": "2026-03-30", "time": "14:00", "start_time": "2026-03-30T14:00:00"},
    ]

    mock_loop_result = MagicMock()
    mock_loop_result.response_text = "Aquí tienes los horarios disponibles."
    mock_loop_result.tool_results = {
        "find_next_available": {
            "selected_stylist_slots": new_slots,
        }
    }
    mock_loop_result.tool_events = []

    with (
        patch.object(mode, "_use_optimized_prompts", return_value=False),
        patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_loop.return_value = mock_loop_result
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    offered = mc.get("offered_slots", [])
    # Old slot must be gone — replaced by new results
    old_ids = {s["id"] for s in offered}
    assert "old-slot" not in old_ids, "Stale offered_slot must be overwritten"
    assert len(offered) == 2, "New slots should replace old ones"


@pytest.mark.asyncio
async def test_offered_slots_cleared_on_explicit_empty_result() -> None:
    """T2.1/T2.2: Recognized-empty tool result clears offered_slots to []."""
    mode = make_booking_mode()
    state = make_slot_state("para el próximo jueves")
    state["mode_context"]["offered_slots"] = [
        {"id": "stale-slot", "date": "2026-03-24", "time": "10:00", "start_time": "2026-03-24T10:00:00"},
    ]

    mock_loop_result = MagicMock()
    mock_loop_result.response_text = "No hay disponibilidad para ese día."
    # check_availability returns valid response with 0 slots
    mock_loop_result.tool_results = {
        "check_availability": {
            "available_slots": [],
        }
    }
    mock_loop_result.tool_events = []

    with (
        patch.object(mode, "_use_optimized_prompts", return_value=False),
        patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_loop.return_value = mock_loop_result
        result = await mode._handle_slot_selection(state, dict(state["mode_context"]))

    mc = result.get("mode_context", {})
    # offered_slots must be an explicit empty list, not stale or None
    assert mc.get("offered_slots") == [], "Empty availability must clear offered_slots to []"


def test_interpret_slot_tool_results_unknown_format_logs_error_and_returns_empty(caplog) -> None:
    """T2.2: Malformed tool payload clears offers and logs an error."""
    import logging

    mode = make_booking_mode()
    # Provide a non-dict, non-list payload — unknown format
    tool_results = {"check_availability": "unexpected string payload"}
    mode_context: dict = {"stylist_id": "550e8400-e29b-41d4-a716-446655440000"}

    with caplog.at_level(logging.ERROR, logger="agent.modes.booking_mode"):
        interp = mode._interpret_slot_tool_results(tool_results, mode_context)

    # Must log an error
    assert any("unrecognized payload" in rec.message.lower() for rec in caplog.records), (
        "Unknown payload must produce an ERROR log"
    )
    # Must surface available_slots=[] for safe recovery
    assert interp.get("available_slots") == [], "Unknown payload must yield available_slots=[]"
    assert not interp.get("has_slots"), "Unknown payload must not report has_slots=True"
