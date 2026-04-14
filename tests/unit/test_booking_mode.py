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
        "add_more_asked": True,
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


# ──────────────────────────────────────────────────────────────────────
# TASK-1: F-8 removal — _build_response always returns sanitized LLM text
# ──────────────────────────────────────────────────────────────────────


def test_build_response_returns_llm_text_always():
    """_build_response returns _sanitize_response(result.response_text) regardless of _booking_completed."""
    from agent.modes.booking_mode import BookingModeNode
    from agent.modes.base import AgenticLoopResult

    node = BookingModeNode(tools=[])
    llm_text = "¡Listo! Tu cita está confirmada. Aquí tu enlace de calendario."
    result = AgenticLoopResult(response_text=llm_text)

    # When _booking_completed is True AND selected_slot is set — no F-8 override
    mode_context = {
        "_booking_completed": True,
        "selected_slot": {"day_label": "Viernes 10", "time": "10:20"},
        "last_stylist": "Pilar",
        "last_services": ["Cortar"],
    }
    response = node._build_response(result, mode_context)
    assert response == llm_text


def test_build_response_empty_llm_text():
    """_build_response with empty response_text returns empty string."""
    from agent.modes.booking_mode import BookingModeNode
    from agent.modes.base import AgenticLoopResult

    node = BookingModeNode(tools=[])
    result = AgenticLoopResult(response_text="")
    response = node._build_response(result, {"_booking_completed": True})
    assert response == ""


def test_render_booking_confirmation_method_removed():
    """_render_booking_confirmation method must no longer exist (F-8 deleted)."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    assert not hasattr(node, "_render_booking_confirmation"), (
        "_render_booking_confirmation was deleted in F-8 removal — must not be present"
    )


# ──────────────────────────────────────────────────────────────────────
# TASK-2: Confirmation gate — book() rejected when step != confirmation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmation_gate_rejects_at_name_collection():
    """book() at name_collection step → ToolCallRejection(CONFIRMATION_REQUIRED)."""
    from agent.modes.booking_mode import BookingModeNode
    from agent.modes.base import ToolCallRejection

    node = BookingModeNode(tools=[])
    # Set up: service + stylist + slot resolved, but NO customer_name
    node._booking_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
        "selected_slot": {"stylist_id": "abc", "start_time": "2026-04-10T10:00:00"},
        "customer_name": None,  # Missing — step = name_collection
        "add_more_asked": True,
    }
    node._mode_context = node._booking_context

    result = await node._pre_tool_call("book", {"customer_first_name": "", "services": ["Cortar"]})

    assert isinstance(result, ToolCallRejection)
    assert result.error_code == "CONFIRMATION_REQUIRED"
    assert "nombre" in result.error_message


@pytest.mark.asyncio
async def test_confirmation_gate_allows_without_notes_asked():
    """book() without notes_asked → allowed (notes are optional, prompt-driven)."""
    from agent.modes.booking_mode import BookingModeNode
    from agent.modes.base import ToolCallRejection

    node = BookingModeNode(tools=[])
    node._booking_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
        "selected_slot": {"stylist_id": "abc", "start_time": "2026-04-10T10:00:00"},
        "customer_name": "Pablo",
        "add_more_asked": True,
    }
    node._mode_context = node._booking_context

    result = await node._pre_tool_call("book", {"services": ["Cortar"]})

    assert not isinstance(result, ToolCallRejection)


@pytest.mark.asyncio
async def test_confirmation_gate_passes_at_confirmation_step():
    """book() at confirmation step → NOT rejected (returns dict, not ToolCallRejection)."""
    from agent.modes.booking_mode import BookingModeNode
    from agent.modes.base import ToolCallRejection

    node = BookingModeNode(tools=[])
    node._booking_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
        "selected_slot": {
            "stylist_id": "abc-123",
            "start_time": "2026-04-10T10:00:00",
            "stylist_name": "Pilar",
        },
        "customer_name": "Pablo",
        "add_more_asked": True,
    }
    node._mode_context = node._booking_context

    result = await node._pre_tool_call("book", {"services": ["Cortar"]})

    assert not isinstance(result, ToolCallRejection), (
        f"Expected dict (pass-through), got ToolCallRejection: {result}"
    )


@pytest.mark.asyncio
async def test_confirmation_gate_persists_slot_on_rejection():
    """Slot resolved in Step A BEFORE gate fires — selected_slot persists even on rejection."""
    from agent.modes.booking_mode import BookingModeNode
    from agent.modes.base import ToolCallRejection

    node = BookingModeNode(tools=[])
    node._booking_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
        "selected_slot": None,
        "offered_slots": [
            {
                "stylist_id": "abc-123",
                "start_time": "2026-04-10T10:00:00",
                "stylist_name": "Pilar",
            }
        ],
        "customer_name": None,  # Will be extracted from args → triggers name_collection → rejected
    }
    node._mode_context = node._booking_context

    result = await node._pre_tool_call(
        "book",
        {
            "slot_index": 1,
            "customer_first_name": "Pablo",  # Extracted in Step A.2
            "services": ["Cortar"],
        },
    )

    # Gate should pass — all required fields present after Step A extractions
    # (notes_asked is no longer a blocking gate)
    assert not isinstance(result, ToolCallRejection)
    # selected_slot MUST be persisted (Step A ran)
    assert node._booking_context["selected_slot"] is not None
    assert node._booking_context["selected_slot"]["stylist_id"] == "abc-123"
    # customer_name MUST be persisted (Step A.2 ran)
    assert node._booking_context["customer_name"] == "Pablo"


# ──────────────────────────────────────────────────────────────────────
# TASK-3: Stylist list in dynamic context at stylist_selection step
# ──────────────────────────────────────────────────────────────────────


def test_build_dynamic_context_includes_available_stylists_at_stylist_selection():
    """_build_dynamic_context includes <available_stylists> at stylist_selection step."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    # Simulate pre-loaded cache
    node._cached_stylists_by_category = {
        "HAIRDRESSING": ["Marta", "Victor", "Pilar"],
        "AESTHETICS": ["Ana"],
    }

    mode_context = {
        "last_services": ["Cortar"],
        "last_service_category": "HAIRDRESSING",
        "booking_step": "stylist_selection",
    }
    state: dict = {"customer_phone": "", "messages": []}

    context = node._build_dynamic_context(mode_context, state)  # type: ignore[arg-type]

    assert "<available_stylists>" in context
    assert "1. Marta" in context
    assert "2. Victor" in context
    assert "3. Pilar" in context
    assert "la primera disponible" in context
    # Ana (AESTHETICS) should NOT appear
    assert "Ana" not in context


def test_build_dynamic_context_excludes_available_stylists_at_other_steps():
    """_build_dynamic_context does NOT include <available_stylists> at non-stylist_selection steps."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    node._cached_stylists_by_category = {"HAIRDRESSING": ["Marta", "Victor"]}

    for step in ("service_selection", "datetime_selection", "name_collection", "confirmation"):
        mode_context = {
            "booking_step": step,
            "last_services": ["Cortar"],
            "last_service_category": "HAIRDRESSING",
            "last_stylist": "Marta",
            "selected_slot": {"stylist_id": "x"},
            "customer_name": "Pablo",
        }
        context = node._build_dynamic_context(mode_context, {"customer_phone": "", "messages": []})  # type: ignore[arg-type]
        assert "<available_stylists>" not in context, (
            f"<available_stylists> should not appear at step '{step}'"
        )


def test_get_stylists_for_services_falls_back_to_all_when_category_unknown():
    """_get_stylists_for_services falls back to all stylists when category is not in cache."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    node._cached_stylists_by_category = {
        "HAIRDRESSING": ["Marta", "Victor"],
        "AESTHETICS": ["Ana"],
    }
    mode_context = {"last_service_category": "UNKNOWN_CAT"}
    names = node._get_stylists_for_services(mode_context)
    # Should return union of all categories, sorted
    assert sorted(names) == ["Ana", "Marta", "Victor"]


def test_get_stylists_for_services_no_cache_returns_empty():
    """_get_stylists_for_services returns [] when cache is empty (e.g. DB down at startup)."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode(tools=[])
    node._cached_stylists_by_category = {}
    names = node._get_stylists_for_services({"last_service_category": "HAIRDRESSING"})
    assert names == []


# ──────────────────────────────────────────────────────────────────────
# TASK-4: Router first-interaction fix
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_router_first_interaction_book_routes_to_greeting():
    """is_first_interaction=True + intent=book → router routes to BOOKING directly."""
    from unittest.mock import AsyncMock, MagicMock, patch

    state = {
        "conversation_id": "test-conv",
        "current_mode": "GREETING",
        "is_first_interaction": True,
        "customer_name": None,
        "error_count": 0,
        "escalation_triggered": False,
        "messages": [{"role": "user", "content": "quiero un corte con Marta"}],
        "booking_context": {},
        "mode_context": {},
        "draft_contexts": {},
        "pending_confirmation_appointment_id": None,
    }

    mock_intent = MagicMock()
    mock_intent.intent = "book"
    mock_intent.confidence = 0.95

    mock_router = MagicMock()
    mock_router.classify = AsyncMock(return_value=mock_intent)

    with (
        patch("agent.graphs.conversation_flow._get_intent_router", return_value=mock_router),
        patch(
            "agent.graphs.conversation_flow._extract_booking_hints",
            new=AsyncMock(
                return_value={"preferred_stylist_name": "Marta", "preferred_date_hint": None}
            ),
        ),
    ):
        from agent.graphs.conversation_flow import router_node

        result = await router_node(state)

    assert result["current_mode"] == "BOOKING", (
        f"Expected BOOKING but got {result.get('current_mode')}"
    )


@pytest.mark.asyncio
async def test_router_first_interaction_escalate_skips_greeting():
    """is_first_interaction=True + intent=escalate → ESCALATION, NOT GREETING."""
    from unittest.mock import AsyncMock, MagicMock, patch

    state = {
        "conversation_id": "test-conv",
        "current_mode": "GREETING",
        "is_first_interaction": True,
        "customer_name": None,
        "error_count": 0,
        "escalation_triggered": False,
        "messages": [{"role": "user", "content": "necesito hablar con una persona"}],
        "booking_context": {},
        "mode_context": {},
        "draft_contexts": {},
        "pending_confirmation_appointment_id": None,
    }

    mock_intent = MagicMock()
    mock_intent.intent = "escalate"
    mock_intent.confidence = 0.9

    mock_router = MagicMock()
    mock_router.classify = AsyncMock(return_value=mock_intent)

    with patch("agent.graphs.conversation_flow._get_intent_router", return_value=mock_router):
        from agent.graphs.conversation_flow import router_node

        result = await router_node(state)

    assert result["current_mode"] == "ESCALATION"


@pytest.mark.asyncio
async def test_router_non_first_interaction_book_routes_to_booking():
    """is_first_interaction=False + intent=book → BOOKING (Rule 8 unchanged)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    state = {
        "conversation_id": "test-conv",
        "current_mode": "GENERAL",
        "is_first_interaction": False,
        "customer_name": "Pablo",
        "error_count": 0,
        "escalation_triggered": False,
        "messages": [{"role": "user", "content": "quiero reservar"}],
        "booking_context": {},
        "mode_context": {},
        "draft_contexts": {},
        "pending_confirmation_appointment_id": None,
    }

    mock_intent = MagicMock()
    mock_intent.intent = "book"
    mock_intent.confidence = 0.95

    mock_router = MagicMock()
    mock_router.classify = AsyncMock(return_value=mock_intent)

    with (
        patch("agent.graphs.conversation_flow._get_intent_router", return_value=mock_router),
        patch(
            "agent.graphs.conversation_flow._extract_booking_hints",
            new=AsyncMock(
                return_value={"preferred_stylist_name": None, "preferred_date_hint": None}
            ),
        ),
    ):
        from agent.graphs.conversation_flow import router_node

        result = await router_node(state)

    assert result["current_mode"] == "BOOKING"


@pytest.mark.asyncio
async def test_greeting_mode_forwards_booking_hints_to_booking():
    """GreetingMode.handle with booking_hints in mode_context → hints forwarded in transition."""
    from unittest.mock import AsyncMock, patch
    from agent.modes.greeting_mode import GreetingMode

    # Simulate state where router put booking_hints in mode_context
    state = {
        "conversation_id": "test-conv",
        "customer_name": None,
        "is_first_interaction": True,
        "ai_disclosure_sent": False,
        "messages": [{"role": "user", "content": "quiero un corte con Marta"}],
        "mode_context": {
            "last_intent": "book",
            "booking_hints": {
                "preferred_stylist_name": "Marta",
                "preferred_date_hint": None,
            },
        },
        "current_mode": "GREETING",
        "booking_context": {},
    }

    node = GreetingMode(tools=[])

    # Patch _render_layered_response to avoid LLM call
    with patch.object(
        node,
        "_render_layered_response",
        new=AsyncMock(return_value="¡Hola! ¿Qué necesitas?"),
    ):
        result = await node.handle(state, None)

    # target_mode should be BOOKING (last_intent="book")
    # booking_context in result should carry preferred_stylist_name (single source of truth)
    booking_ctx = result.get("booking_context") or {}
    assert booking_ctx.get("preferred_stylist_name") == "Marta", (
        f"booking_hints not forwarded to booking_context: {booking_ctx}"
    )
