"""
B.5.1 — assert that legacy _dynamic_context_* attributes have been removed from
BookingModeNode (they were instance attributes set by _build_dynamic_context,
which was deleted in B.1.6).
"""

from __future__ import annotations

from agent.modes.booking_mode import BookingModeNode


def test_no_dynamic_context_index_attr() -> None:
    """_dynamic_context_index must not exist on BookingModeNode (removed in B.1.6)."""
    assert not hasattr(BookingModeNode, "_dynamic_context_index"), (
        "BookingModeNode still has _dynamic_context_index — orphan from deleted "
        "_build_dynamic_context path"
    )


def test_no_dynamic_context_state_attr() -> None:
    """_dynamic_context_state must not exist on BookingModeNode (removed in B.1.6)."""
    assert not hasattr(BookingModeNode, "_dynamic_context_state"), (
        "BookingModeNode still has _dynamic_context_state — orphan from deleted "
        "_build_dynamic_context path"
    )


def test_no_refresh_dynamic_context_method() -> None:
    """_refresh_dynamic_context must not exist on BookingModeNode (removed in B.1.6)."""
    assert not hasattr(BookingModeNode, "_refresh_dynamic_context"), (
        "BookingModeNode still has _refresh_dynamic_context — orphan from deleted "
        "_build_dynamic_context path"
    )


def test_no_build_dynamic_context_method() -> None:
    """_build_dynamic_context must not exist on BookingModeNode (deleted in B.1.6)."""
    assert not hasattr(
        BookingModeNode, "_build_dynamic_context"
    ), "BookingModeNode still has _build_dynamic_context — must be removed per B.1.6"
