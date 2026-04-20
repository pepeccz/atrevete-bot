"""
RED tests for B.3.3 — field writer inventory.

Instruments BookingContext via a write-counting proxy.
Drives a scripted 2-turn booking scenario via direct handle() invocation
with mocked LLM and tools.
Asserts that flow-control fields have at most 1 write per field per turn.

Must FAIL on master because multiple writers fire for some fields.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Write-counting proxy
# ---------------------------------------------------------------------------


class WriteCountingDict(dict):
    """Dict subclass that counts writes per key."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._write_counts: dict[str, int] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self._write_counts[key] = self._write_counts.get(key, 0) + 1
        super().__setitem__(key, value)

    def write_count(self, key: str) -> int:
        return self._write_counts.get(key, 0)

    def reset_counts(self) -> None:
        self._write_counts.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FLOW_CONTROL_FIELDS = [
    "confirmed",
    "add_more_asked",
    "selected_slot",
    "last_stylist",
    "last_services",
    "notes",
    "notes_state",
]


def _make_state(booking_context: dict, user_msg: str = "nada más") -> dict:
    return {
        "conversation_id": "test-field-inventory-001",
        "current_mode": "BOOKING",
        "messages": [{"role": "user", "content": user_msg}],
        "booking_context": booking_context,
        "total_message_count": 2,
        "customer_phone": "+34600000000",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_confirmed_written_at_most_once_per_turn() -> None:
    """confirmed must be written at most once per turn (pre-loop resolver only)."""
    from agent.booking.patch_pipeline import apply_resolver_patch  # noqa: PLC0415
    from infra.resolvers.affirmation import is_affirmation  # noqa: PLC0415

    bc = WriteCountingDict(
        _confirmation_shown=True,
        confirmed=None,
        last_services=["Corte largo"],
        add_more_asked=True,
    )

    # Simulate pre-loop: only one resolver should write confirmed
    user_msg = "sí, dale"
    if bc.get("_confirmation_shown") and bc.get("confirmed") is None:
        if is_affirmation(user_msg):
            apply_resolver_patch(
                bc,
                {
                    "source": "is_affirmation",
                    "matched": True,
                    "patch": {"confirmed": True},
                    "reason": "affirmation",
                },
                conversation_id="test",
                turn=2,
            )

    assert (
        bc.write_count("confirmed") <= 1
    ), f"'confirmed' was written {bc.write_count('confirmed')} times in one turn"


def test_add_more_asked_written_at_most_once_per_turn() -> None:
    """add_more_asked must be written at most once per turn (negation resolver only)."""
    from agent.booking.patch_pipeline import (
        apply_resolver_patch,
        resolve_add_more_negation,
    )  # noqa: PLC0415

    bc = WriteCountingDict(
        _confirmation_shown=False,
        confirmed=None,
        last_services=["Corte largo"],
        add_more_asked=False,
    )
    state = _make_state(dict(bc), user_msg="nada más")

    # Only the negation resolver should write add_more_asked
    result = resolve_add_more_negation("nada más", state, bc)
    if result:
        apply_resolver_patch(bc, result, conversation_id="test", turn=2)

    assert (
        bc.write_count("add_more_asked") <= 1
    ), f"'add_more_asked' was written {bc.write_count('add_more_asked')} times in one turn"


def test_no_extra_writes_in_post_tool_check_availability() -> None:
    """_post_tool_result[check_availability] must NOT write last_services, last_stylist,
    or last_total_duration_minutes (those come only via update_booking patch).
    """
    import asyncio  # noqa: PLC0415

    from agent.modes.booking_mode import BookingModeNode  # noqa: PLC0415

    node = BookingModeNode(tools=[])
    bc = WriteCountingDict(
        last_services=["Corte largo"],
        last_stylist="Ana",
        last_total_duration_minutes=60,
        add_more_asked=True,
    )
    node._booking_context = bc
    node._mode_context = bc

    result = {
        "available_slots": [{"stylist_name": "Ana", "start_time": "2026-04-22T10:00:00"}],
        "total_duration_minutes": 75,
    }
    tool_args = {
        "service_names": ["Corte Largo Extra"],
        "stylist_name": "María",
    }

    asyncio.get_event_loop().run_until_complete(
        node._post_tool_result("check_availability", tool_args, result)
    )

    # These fields must NOT have been written by _post_tool_result[check_availability]
    assert (
        bc.write_count("last_services") == 0
    ), f"last_services written {bc.write_count('last_services')} times by check_availability"
    assert (
        bc.write_count("last_stylist") == 0
    ), f"last_stylist written {bc.write_count('last_stylist')} times by check_availability"
    assert bc.write_count("last_total_duration_minutes") == 0, (
        "last_total_duration_minutes written "
        f"{bc.write_count('last_total_duration_minutes')} times by check_availability"
    )
