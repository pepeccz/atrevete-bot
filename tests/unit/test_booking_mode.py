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


def test_no_booking_context():
    """BookingContext is not used in booking_mode — replaced by flat dict mode_context."""
    import agent.modes.booking_mode as module

    source = inspect.getsource(module)
    assert "BookingContext" not in source, (
        "BookingContext should be removed — mode_context is now a plain dict"
    )


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

    node = BookingModeNode()
    assert node.mode_name == "BOOKING"


# ──────────────────────────────────────────────────────────────────────
# _pre_tool_call: customer_name extraction from book() args
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def booking_node():
    """Create a BookingModeNode with a mutable _mode_context for testing."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode()
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


@pytest.mark.asyncio
async def test_pre_tool_call_name_extraction_triggers_confirmation_summary(booking_node):
    """Spec scenario 5: name extraction + complete data → ToolCallRejection with summary."""
    from agent.modes.base import ToolCallRejection

    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Pilar",
        "selected_slot": {
            "day_label": "Viernes 10",
            "time": "10:20",
            "stylist_id": "abc-123",
            "start_time": "2026-04-10T10:20:00",
        },
        "offered_slots": [
            {
                "day_label": "Viernes 10",
                "time": "10:20",
                "stylist_id": "abc-123",
                "start_time": "2026-04-10T10:20:00",
                "stylist_name": "Pilar",
            }
        ],
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
    # Gate should reject with confirmation summary
    assert isinstance(result, ToolCallRejection)
    assert result.error_code == "CONFIRMATION_NOT_SHOWN"
    assert "María García" in result.error_message or "Cortar" in result.error_message
