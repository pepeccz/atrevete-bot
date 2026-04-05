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
