"""
Tests for agent/modes/booking_mode.py — simplified LLM-driven architecture.

Verifies:
- BookingModeNode is importable
- BookingContext was removed (flat dict replaces it)
- Old tools (search_services, list_stylists, create_hold) are not present
"""

import inspect

import pytest


def test_importable():
    """BookingModeNode is importable from agent.modes.booking_mode."""
    from agent.modes.booking_mode import BookingModeNode

    assert BookingModeNode is not None


def test_booking_context_state_field_used():
    """booking_context state field is used in handle() — replaces flat dict mode_context for booking data."""
    import agent.modes.booking_mode as module

    source = inspect.getsource(module)
    # Phase 1+2: booking_context is now the canonical store for booking data
    assert "booking_context" in source, "booking_context state field should be used in booking_mode"
    # The handle() method must load from state["booking_context"]
    assert 'state.get("booking_context")' in source, "handle() must load booking_context from state"


def test_no_old_tools():
    """search_services, list_stylists, create_hold are not referenced in booking_mode."""
    import agent.modes.booking_mode as module

    source = inspect.getsource(module)
    assert "search_services" not in source, (
        "search_services tool was removed in the simplified architecture"
    )
    assert "list_stylists" not in source, (
        "list_stylists tool was removed — stylists are shown via the catalog in the prompt"
    )
    assert "create_hold" not in source, (
        "create_hold tool was removed — slots are confirmed directly without a hold step"
    )


def test_mode_name_is_booking():
    """BookingModeNode.mode_name returns 'BOOKING'."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    assert node.mode_name == "BOOKING"


# ──────────────────────────────────────────────────────────────────────
# _pre_tool_call: customer_name extraction from book() args
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def booking_node():
    """Create a BookingModeNode with a mutable _mode_context for testing."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    node._mode_context = {}
    return node


@pytest.mark.asyncio
async def test_pre_tool_call_extracts_first_and_last_name(booking_node):
    """Spec scenario 1: first + last name → 'María García' in mode_context."""
    booking_node._mode_context = {}
    tool_args = {
        "customer_first_name": "María",
        "customer_last_name": "García",
        "customer_phone": "+34612345678",
        "services": ["Cortar"],
        "slot_index": 1,
    }

    await booking_node._pre_tool_call("book", tool_args)

    assert booking_node._mode_context["customer_name"] == "María García"


@pytest.mark.asyncio
async def test_pre_tool_call_extracts_first_name_only(booking_node):
    """Spec scenario 2: first name only, last_name=None → 'María'."""
    booking_node._mode_context = {}
    tool_args = {
        "customer_first_name": "María",
        "customer_last_name": None,
        "customer_phone": "+34612345678",
        "services": ["Cortar"],
        "slot_index": 1,
    }

    await booking_node._pre_tool_call("book", tool_args)

    assert booking_node._mode_context["customer_name"] == "María"


@pytest.mark.asyncio
async def test_pre_tool_call_no_overwrite_existing_name(booking_node):
    """Spec scenario 3: existing name not overwritten by new book() args."""
    booking_node._mode_context = {"customer_name": "Pablo Cabeza"}
    tool_args = {
        "customer_first_name": "Pablo",
        "customer_last_name": None,
        "customer_phone": "+34612345678",
        "services": ["Cortar"],
        "slot_index": 1,
    }

    await booking_node._pre_tool_call("book", tool_args)

    assert booking_node._mode_context["customer_name"] == "Pablo Cabeza"


@pytest.mark.asyncio
async def test_pre_tool_call_rejects_empty_name(booking_node):
    """Spec scenario 4: empty customer_first_name → name NOT set."""
    booking_node._mode_context = {}
    tool_args = {
        "customer_first_name": "",
        "customer_last_name": None,
        "customer_phone": "+34612345678",
        "services": ["Cortar"],
        "slot_index": 1,
    }

    await booking_node._pre_tool_call("book", tool_args)

    assert booking_node._mode_context.get("customer_name") is None


# ──────────────────────────────────────────────────────────────────────
# Static analysis: no state.get("user_message") reads in agent/modes/
# (Task 4.6 — agent-state-architecture-fix)
# ──────────────────────────────────────────────────────────────────────


def test_no_user_message_reads_in_modes():
    """Verify zero state.get('user_message') reads in agent/modes/ (excluding writes)."""
    import re
    from pathlib import Path

    modes_dir = Path("agent/modes")
    violations = []
    for py_file in modes_dir.glob("*.py"):
        content = py_file.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            if 'state.get("user_message")' in line or "state.get('user_message')" in line:
                # Exclude write assignments like "user_message": None
                if '"user_message": None' not in line and "'user_message': None" not in line:
                    violations.append(f"{py_file.name}:{i}: {line.strip()}")
    assert violations == [], f"Found user_message reads in modes: {violations}"


@pytest.mark.asyncio
async def test_pre_tool_call_name_extraction_and_slot_injection(booking_node):
    """Spec scenario 5: name extraction + slot_index resolution → tool_args updated, no gate."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
        "selected_slot": None,
        "offered_slots": [
            {
                "day_label": "Viernes 10",
                "time": "10:20",
                "stylist_id": "abc-123",
                "start_time": "2026-04-10T10:20:00",
                "stylist_name": "Pilar",
            }
        ],
        "notes_asked": True,
    }
    tool_args = {
        "customer_first_name": "María",
        "customer_last_name": "García",
        "customer_phone": "+34612345678",
        "services": ["Cortar"],
        "slot_index": 1,
    }

    result = await booking_node._pre_tool_call("book", tool_args)

    # Name should be extracted
    assert booking_node._mode_context["customer_name"] == "María García"
    # Slot should be resolved — no confirmation gate, call proceeds through
    assert result["stylist_id"] == "abc-123"
    assert result["start_time"] == "2026-04-10T10:20:00"


# ──────────────────────────────────────────────────────────────────────
# offered_slots lifecycle: _pre_tool_call does NOT wipe, _post_tool_result
# clears stale state ONLY when new slots arrive successfully (R-MOD-1)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pre_tool_call_check_availability_does_not_wipe_slots(booking_node):
    """check_availability call must NOT eagerly wipe offered_slots from booking_context."""
    original_slots = [{"stylist_id": "uuid-1", "start_time": "2026-04-15T10:00"}]
    booking_node._booking_context = {
        "offered_slots": original_slots,
        "last_stylist": "Pilar",
    }
    booking_node._mode_context = booking_node._booking_context

    await booking_node._pre_tool_call("check_availability", {"service_names": ["CORTE LARGO"], "stylist_name": "Pilar"})

    assert booking_node._booking_context["offered_slots"] == original_slots


@pytest.mark.asyncio
async def test_post_tool_result_check_availability_clears_and_updates_slots(booking_node):
    """_post_tool_result clears stale selected_slot and updates offered_slots when new slots arrive."""
    import json

    old_slots = [{"stylist_id": "old", "start_time": "old"}]
    booking_node._booking_context = {
        "offered_slots": old_slots,
        "selected_slot": {"stylist_id": "old"},
        "last_stylist": "Pilar",
    }
    booking_node._mode_context = booking_node._booking_context

    new_slots = [
        {"stylist_id": "uuid-2", "start_time": "2026-04-16T11:00"},
        {"stylist_id": "uuid-3", "start_time": "2026-04-17T09:00"},
    ]
    await booking_node._post_tool_result(
        "check_availability",
        {"stylist_name": "Pilar"},
        json.dumps({"available_slots": new_slots}),
    )

    assert booking_node._booking_context["offered_slots"] == new_slots
    assert booking_node._booking_context.get("selected_slot") is None


@pytest.mark.asyncio
async def test_post_tool_result_check_availability_empty_result_preserves_slots(booking_node):
    """_post_tool_result must NOT clear offered_slots or selected_slot when result is empty."""
    import json

    original_slots = [{"stylist_id": "uuid-1", "start_time": "2026-04-15T10:00"}]
    original_slot = {"stylist_id": "uuid-1"}
    booking_node._booking_context = {
        "offered_slots": original_slots,
        "selected_slot": original_slot,
        "last_stylist": "Pilar",
    }
    booking_node._mode_context = booking_node._booking_context

    await booking_node._post_tool_result(
        "check_availability",
        {"stylist_name": "Pilar"},
        json.dumps({"available_slots": []}),
    )

    assert booking_node._booking_context["offered_slots"] == original_slots
    assert booking_node._booking_context["selected_slot"] == original_slot


# ──────────────────────────────────────────────────────────────────────
# TASK-5: Write path — _post_tool_result calls write_customer_memories
#         on successful book() result.
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def booking_node_with_state():
    """BookingModeNode with _current_state and _booking_context pre-set."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    node._booking_context = {
        "last_services": ["CORTE LARGO"],
        "last_stylist": "Pilar",
        "selected_slot": {
            "stylist_id": "stylist-uuid-123",
            "start_time": "2026-04-15T10:00:00+02:00",
            "day_label": "Martes 15",
            "time": "10:00",
        },
        "no_preference_stylist": False,
        "notes": "alergia al amoniaco",
    }
    node._mode_context = node._booking_context
    node._current_state = {
        "customer_phone": "+34612345678",
        "customer_memories": {"visit_count": 2, "preferred_stylist_name": "Pilar"},
    }
    return node


@pytest.mark.asyncio
async def test_post_tool_result_book_ok_calls_write(booking_node_with_state):
    """book() returns status=ok → write_customer_memories awaited with correct args."""
    import json
    from unittest.mock import AsyncMock, patch

    with patch(
        "agent.modes.booking_mode.write_customer_memories",
        new=AsyncMock(),
    ) as mock_write:
        await booking_node_with_state._post_tool_result(
            "book",
            {},
            json.dumps({"status": "ok", "appointment_id": "appt-uuid"}),
        )

    mock_write.assert_awaited_once()
    call_phone, call_booking_data, call_existing_prefs = mock_write.call_args.args
    assert call_phone == "+34612345678"
    assert call_existing_prefs == {"visit_count": 2, "preferred_stylist_name": "Pilar"}


@pytest.mark.asyncio
async def test_post_tool_result_book_ok_booking_data_fields(booking_node_with_state):
    """Booking data passed to write contains correct fields from booking_context."""
    import json
    from unittest.mock import AsyncMock, patch

    with patch(
        "agent.modes.booking_mode.write_customer_memories",
        new=AsyncMock(),
    ) as mock_write:
        await booking_node_with_state._post_tool_result(
            "book",
            {},
            json.dumps({"status": "ok", "appointment_id": "appt-uuid"}),
        )

    _, call_booking_data, _ = mock_write.call_args.args
    assert call_booking_data["service_names"] == ["CORTE LARGO"]
    assert call_booking_data["stylist_id"] == "stylist-uuid-123"
    assert call_booking_data["start_time"] == "2026-04-15T10:00:00+02:00"
    assert call_booking_data["no_preference_stylist"] is False
    assert call_booking_data["notes"] == "alergia al amoniaco"


@pytest.mark.asyncio
async def test_post_tool_result_book_failure_no_write(booking_node_with_state):
    """book() returns status=error → write_customer_memories NOT called."""
    import json
    from unittest.mock import AsyncMock, patch

    with patch(
        "agent.modes.booking_mode.write_customer_memories",
        new=AsyncMock(),
    ) as mock_write:
        await booking_node_with_state._post_tool_result(
            "book",
            {},
            json.dumps({"status": "error", "message": "slot taken"}),
        )

    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_tool_result_book_write_exception_booking_completed_still_true(
    booking_node_with_state,
):
    """write_customer_memories raises → _booking_completed is still True, no re-raise."""
    import json
    from unittest.mock import AsyncMock, patch

    with patch(
        "agent.modes.booking_mode.write_customer_memories",
        new=AsyncMock(side_effect=RuntimeError("Store down")),
    ):
        # Must not raise
        await booking_node_with_state._post_tool_result(
            "book",
            {},
            json.dumps({"status": "ok", "appointment_id": "appt-uuid"}),
        )

    assert booking_node_with_state._booking_context["_booking_completed"] is True


@pytest.mark.asyncio
async def test_post_tool_result_book_no_phone_skips_write():
    """customer_phone is None → write_customer_memories NOT called."""
    import json
    from unittest.mock import AsyncMock, patch
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    node._booking_context = {
        "last_services": ["CORTE"],
        "selected_slot": {"stylist_id": "uuid", "start_time": "2026-04-15T10:00:00"},
    }
    node._mode_context = node._booking_context
    node._current_state = {"customer_phone": None}

    with patch(
        "agent.modes.booking_mode.write_customer_memories",
        new=AsyncMock(),
    ) as mock_write:
        await node._post_tool_result(
            "book",
            {},
            json.dumps({"status": "ok", "appointment_id": "appt-uuid"}),
        )

    mock_write.assert_not_awaited()
    # booking_completed should still be True even without phone
    assert node._booking_context["_booking_completed"] is True


@pytest.mark.asyncio
async def test_post_tool_result_book_passes_existing_prefs_from_state(booking_node_with_state):
    """existing_prefs comes from _current_state['customer_memories']."""
    import json
    from unittest.mock import AsyncMock, patch

    existing = {"visit_count": 5, "preferred_stylist_name": "Maria"}
    booking_node_with_state._current_state["customer_memories"] = existing

    with patch(
        "agent.modes.booking_mode.write_customer_memories",
        new=AsyncMock(),
    ) as mock_write:
        await booking_node_with_state._post_tool_result(
            "book",
            {},
            json.dumps({"status": "ok", "appointment_id": "appt-uuid"}),
        )

    _, _, call_existing_prefs = mock_write.call_args.args
    assert call_existing_prefs == existing


@pytest.mark.asyncio
async def test_post_tool_result_book_first_time_existing_prefs_none():
    """_current_state has no customer_memories → existing_prefs=None passed."""
    import json
    from unittest.mock import AsyncMock, patch
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    node._booking_context = {
        "last_services": ["CORTE"],
        "selected_slot": {"stylist_id": "uuid", "start_time": "2026-04-15T10:00:00"},
    }
    node._mode_context = node._booking_context
    # No customer_memories key at all
    node._current_state = {"customer_phone": "+34699000000"}

    with patch(
        "agent.modes.booking_mode.write_customer_memories",
        new=AsyncMock(),
    ) as mock_write:
        await node._post_tool_result(
            "book",
            {},
            json.dumps({"status": "ok", "appointment_id": "appt-uuid"}),
        )

    _, _, call_existing_prefs = mock_write.call_args.args
    assert call_existing_prefs is None
