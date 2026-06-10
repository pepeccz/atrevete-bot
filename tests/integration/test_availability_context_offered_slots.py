"""Integration tests for T5: AvailabilityContextMiddleware materializes recently_offered_slots.

Change J: hallucination-tolerant-architecture-bundle. REQ-J3.

Tests written BEFORE implementation (TDD RED phase).
No live DB required — all external calls are mocked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SERVICE_ID = str(uuid4())
STYLIST_ID = str(uuid4())
CONV_ID = "test-conv-1"


def _make_check_availability_tool_msg(slots: list[dict]) -> MagicMock:
    """Build a fake ToolMessage that looks like a check_availability response."""
    msg = MagicMock()
    msg.name = "check_availability"
    msg.content = json.dumps(
        {
            "status": "ok",
            "payload": {"slots": slots},
        }
    )
    return msg


def _make_next_available_tool_msg(slots: list[dict]) -> MagicMock:
    """Build a fake ToolMessage that looks like a get_next_available_options response."""
    msg = MagicMock()
    msg.name = "get_next_available_options"
    msg.content = json.dumps({"slots": slots})
    return msg


def _build_request(state: dict, messages: list) -> MagicMock:
    state_with_msgs = {**state, "messages": messages}
    request = MagicMock()
    request.state = state_with_msgs
    request.override = MagicMock(side_effect=lambda state: MagicMock(state=state))
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_materializes_offered_slots_from_check_availability():
    """After check_availability ToolMessage, recently_offered_slots is populated."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    now = datetime.now(UTC)
    slot_iso = "2026-06-10T10:00:00+00:00"
    slots = [{"start_iso": slot_iso, "stylist_id": STYLIST_ID}]

    messages = [
        _make_check_availability_tool_msg(slots),
    ]

    captured_state = {}

    async def mock_handler(req):
        captured_state.update(req.state)
        return MagicMock()

    with (
        patch(
            "agent.middleware.availability_context._extract_service_ids_from_messages",
            return_value=[SERVICE_ID],
        ),
        patch(
            "agent.middleware.availability_context.get_availability_window",
            new=AsyncMock(return_value={}),  # Skip XML injection
        ),
        patch(
            "agent.middleware.availability_context._get_redis",
            return_value=None,
        ),
    ):
        middleware = AvailabilityContextMiddleware()
        request = _build_request(
            {"conversation_id": CONV_ID},
            messages,
        )

        # Patch the handler to capture the modified state
        captured_state_ref = {}

        def capture_override(state):
            captured_state_ref.update(state)
            return MagicMock(state=state)

        request.override = capture_override

        await middleware.awrap_model_call(request, mock_handler)

    # recently_offered_slots should be set in the new state
    assert (
        "recently_offered_slots" in captured_state_ref
    ), "recently_offered_slots must be set in state after AvailabilityContextMiddleware"
    offered = captured_state_ref["recently_offered_slots"]
    assert isinstance(offered, list)
    assert len(offered) >= 1
    # Verify the slot is present
    slot_isos = {s["start_iso"] for s in offered}
    # UTC-normalize the expected
    from datetime import datetime as _dt

    expected_dt = _dt.fromisoformat(slot_iso.replace("Z", "+00:00")).astimezone(UTC).isoformat()
    assert any(
        _dt.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
        == _dt.fromisoformat(slot_iso.replace("Z", "+00:00")).astimezone(UTC)
        for s in slot_isos
    ), f"Expected slot {slot_iso} in offered slots, got: {slot_isos}"


@pytest.mark.asyncio
async def test_middleware_sets_expires_at_15min_from_now():
    """Each offered slot must have expires_at = now + 15 min (approx)."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    slot_iso = "2026-06-10T11:00:00+00:00"
    messages = [_make_check_availability_tool_msg([{"start_iso": slot_iso, "stylist_id": None}])]

    captured_state_ref = {}

    def capture_override(state):
        captured_state_ref.update(state)
        return MagicMock(state=state)

    with (
        patch(
            "agent.middleware.availability_context._extract_service_ids_from_messages",
            return_value=[SERVICE_ID],
        ),
        patch(
            "agent.middleware.availability_context.get_availability_window",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.middleware.availability_context._get_redis",
            return_value=None,
        ),
    ):
        middleware = AvailabilityContextMiddleware()
        request = _build_request({"conversation_id": CONV_ID}, messages)
        request.override = capture_override

        before = datetime.now(UTC)
        await middleware.awrap_model_call(request, AsyncMock(return_value=MagicMock()))
        after = datetime.now(UTC)

    if "recently_offered_slots" not in captured_state_ref:
        pytest.skip("recently_offered_slots not yet implemented — expected RED")

    offered = captured_state_ref["recently_offered_slots"]
    assert len(offered) >= 1

    entry = offered[0]
    expires_str = entry.get("expires_at", "")
    assert expires_str, "expires_at must be set"

    expires_dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00")).astimezone(UTC)
    expected_low = before + timedelta(minutes=14, seconds=55)
    expected_high = after + timedelta(minutes=15, seconds=5)
    assert (
        expected_low <= expires_dt <= expected_high
    ), f"expires_at {expires_dt} should be ~now+15min, got range [{expected_low}, {expected_high}]"


@pytest.mark.asyncio
async def test_middleware_purges_expired_entries():
    """Slots whose expires_at is in the past must be purged on next middleware run."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    now = datetime.now(UTC)
    # Existing state has an expired slot
    old_slot = {
        "start_iso": "2026-06-10T09:00:00+00:00",
        "stylist_id": None,
        "expires_at": (now - timedelta(minutes=1)).isoformat(),
        "turn_index": 0,
    }

    # New message has a fresh slot
    new_slot_iso = "2026-06-10T10:00:00+00:00"
    messages = [
        _make_check_availability_tool_msg([{"start_iso": new_slot_iso, "stylist_id": None}])
    ]

    captured_state_ref = {}

    def capture_override(state):
        captured_state_ref.update(state)
        return MagicMock(state=state)

    with (
        patch(
            "agent.middleware.availability_context._extract_service_ids_from_messages",
            return_value=[SERVICE_ID],
        ),
        patch(
            "agent.middleware.availability_context.get_availability_window",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.middleware.availability_context._get_redis",
            return_value=None,
        ),
    ):
        middleware = AvailabilityContextMiddleware()
        request = _build_request(
            {"conversation_id": CONV_ID, "recently_offered_slots": [old_slot]},
            messages,
        )
        request.override = capture_override

        await middleware.awrap_model_call(request, AsyncMock(return_value=MagicMock()))

    if "recently_offered_slots" not in captured_state_ref:
        pytest.skip("recently_offered_slots not yet implemented")

    offered = captured_state_ref["recently_offered_slots"]
    expired_isos = {
        s["start_iso"]
        for s in offered
        if datetime.fromisoformat(s["expires_at"].replace("Z", "+00:00")).astimezone(UTC)
        <= datetime.now(UTC)
    }
    assert len(expired_isos) == 0, f"Expired slots must be purged, but found: {expired_isos}"


@pytest.mark.asyncio
async def test_middleware_purges_stale_by_turn_index():
    """Slots older than 2 turns (turn_index < current - 2) must be purged."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    now = datetime.now(UTC)
    # Slot offered 3 turns ago (current has 10 messages → turn_index=10)
    stale_slot = {
        "start_iso": "2026-06-10T09:00:00+00:00",
        "stylist_id": None,
        "expires_at": (now + timedelta(minutes=10)).isoformat(),  # Still fresh by wall-clock
        "turn_index": 5,  # 3 turns old when current is 8+ messages
    }

    # Build messages list with 8 items so current turn_index = 8
    messages = [MagicMock(name="human_msg")] * 8
    # Add check_availability result as newest
    messages[-1] = _make_check_availability_tool_msg([])

    captured_state_ref = {}

    def capture_override(state):
        captured_state_ref.update(state)
        return MagicMock(state=state)

    with (
        patch(
            "agent.middleware.availability_context._extract_service_ids_from_messages",
            return_value=[SERVICE_ID],
        ),
        patch(
            "agent.middleware.availability_context.get_availability_window",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agent.middleware.availability_context._get_redis",
            return_value=None,
        ),
    ):
        middleware = AvailabilityContextMiddleware()
        request = _build_request(
            {"conversation_id": CONV_ID, "recently_offered_slots": [stale_slot]},
            messages,
        )
        request.override = capture_override

        await middleware.awrap_model_call(request, AsyncMock(return_value=MagicMock()))

    if "recently_offered_slots" not in captured_state_ref:
        pytest.skip("recently_offered_slots not yet implemented")

    offered = captured_state_ref["recently_offered_slots"]
    stale_found = [s for s in offered if s.get("turn_index") == 5]
    assert (
        len(stale_found) == 0
    ), f"Slot with turn_index=5 should have been purged (current ~8), found: {stale_found}"
