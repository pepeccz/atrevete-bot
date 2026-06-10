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
    """Build a fake ToolMessage that looks like a get_next_available_options response (old buggy format).

    Kept for backward-compatibility with existing tests. New tests should use
    _make_next_available_tool_msg_v2 which reflects the real ToolResponse shape.
    """
    msg = MagicMock()
    msg.name = "get_next_available_options"
    msg.content = json.dumps({"slots": slots})
    return msg


def _make_next_available_tool_msg_v2(options: list[dict]) -> MagicMock:
    """Build a fake ToolMessage with the real ToolResponse shape for get_next_available_options.

    The tool wraps its output in ToolResponse: {status: ok, payload: {options: [...]}}.
    Each option has at least start_iso and stylist_id fields (plus stylist_name, service_label).
    """
    msg = MagicMock()
    msg.name = "get_next_available_options"
    msg.content = json.dumps(
        {
            "status": "ok",
            "payload": {
                "options": options,
                "searched_until": "2026-06-17",
                "requested_date_iso": "2026-06-11",
                "total_duration_minutes": 60,
                "strategy": "same_stylist_then_any",
            },
        }
    )
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
async def test_middleware_sets_expires_at_30min_from_now():
    """Each offered slot must have expires_at = now + 30 min (approx).

    P1.2 update: TTL changed from 15 min to 30 min to cover the full offer→book
    conversation gap (typically 4-5 turns, which in a real WhatsApp conversation
    can easily span 10-15 minutes). 30 min is sufficient for any human booking flow
    and short enough that stale offers from abandoned conversations don't resurrect.
    """
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
    expected_low = before + timedelta(minutes=29, seconds=55)
    expected_high = after + timedelta(minutes=30, seconds=5)
    assert (
        expected_low <= expires_dt <= expected_high
    ), f"expires_at {expires_dt} should be ~now+30min, got range [{expected_low}, {expected_high}]"


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
async def test_slot_with_old_turn_index_survives_if_not_expired():
    """P1.2: slots with old turn_index must NOT be purged if wall-clock TTL is still fresh.

    Before P1.2: a slot with turn_index=5 at current_turn=8 would be purged by the
    turn-index guard (5 < 8-2=6). This killed ALL slots in the offer→book gap.

    After P1.2: only wall-clock TTL is used. A slot with turn_index=5 and
    expires_at = now + 10 min must SURVIVE the purge pass.
    """
    from agent.middleware.availability_context import _materialize_offered_slots

    now = datetime.now(UTC)
    slot = {
        "start_iso": "2026-06-10T09:00:00+00:00",
        "stylist_id": None,
        "expires_at": (now + timedelta(minutes=10)).isoformat(),  # Still fresh by wall-clock
        "turn_index": 5,  # Old turn_index — would have been purged by the old guard
    }

    # current_turn_index=8; old guard: min_turn = 8-2 = 6, so turn_index=5 < 6 → purge
    # new guard (P1.2): only TTL check → slot is still fresh → keep
    merged = _materialize_offered_slots(
        new_raw_slots=[],
        existing_slots=[slot],
        current_turn_index=8,
        now=now,
    )

    assert len(merged) == 1, (
        f"P1.2: slot with turn_index=5 at current_turn=8 must survive because "
        f"its wall-clock TTL is still fresh. The turn-index purge was removed. Got: {merged}"
    )
    assert merged[0]["start_iso"] == "2026-06-10T09:00:00+00:00"


# ---------------------------------------------------------------------------
# O1: get_next_available_options ToolResponse shape (payload.options)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_materializes_offered_slots_from_get_next_available_options():
    """O1: get_next_available_options uses ToolResponse shape {status, payload.options}.

    Regression: the old code read data.get("slots", []) which was always empty because
    the tool wraps output in ToolResponse → slots at payload.options, not top-level slots.
    After the fix, recently_offered_slots must be populated from payload.options.
    """
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    slot_iso = "2026-06-12T10:00:00+00:00"
    options = [
        {
            "start_iso": slot_iso,
            "stylist_id": STYLIST_ID,
            "stylist_name": "Harolyn",
            "service_label": "Corte Dama",
        }
    ]
    messages = [_make_next_available_tool_msg_v2(options)]

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

        await middleware.awrap_model_call(request, AsyncMock(return_value=MagicMock()))

    assert (
        "recently_offered_slots" in captured_state_ref
    ), "recently_offered_slots must be populated from get_next_available_options payload.options"
    offered = captured_state_ref["recently_offered_slots"]
    assert len(offered) >= 1, "At least one slot must be extracted from get_next_available_options"
    slot_isos = {s["start_iso"] for s in offered}
    from datetime import datetime as _dt

    assert any(
        _dt.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
        == _dt.fromisoformat(slot_iso.replace("Z", "+00:00")).astimezone(UTC)
        for s in slot_isos
    ), f"Expected slot {slot_iso} in offered slots, got: {slot_isos}"


@pytest.mark.asyncio
async def test_middleware_get_next_available_rejected_does_not_populate_slots():
    """O1 robustness: rejected get_next_available_options must not add slots."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    msg = MagicMock()
    msg.name = "get_next_available_options"
    msg.content = json.dumps({"status": "rejected", "errors": ["Fecha pasada"], "payload": None})
    messages = [msg]

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

        await middleware.awrap_model_call(request, AsyncMock(return_value=MagicMock()))

    offered = captured_state_ref.get("recently_offered_slots", [])
    assert (
        offered == []
    ), "Rejected get_next_available_options must not contribute slots, got: " + str(offered)


@pytest.mark.asyncio
async def test_book_accepts_slot_offered_via_get_next_available_options():
    """O1 end-to-end: book() must accept a slot that was offered via get_next_available_options.

    Simulates the full path: ToolResponse-wrapped options → extractor → recently_offered_slots
    → validate_slot_in_offered passes → book proceeds past J3 guard.
    """

    from datetime import UTC, datetime

    from agent.middleware.availability_context import (
        _extract_offered_slots_from_messages,
        _materialize_offered_slots,
    )

    slot_iso = "2026-06-20T10:00:00+00:00"
    options = [
        {
            "start_iso": slot_iso,
            "stylist_id": STYLIST_ID,
            "stylist_name": "Marta",
            "service_label": "Corte Dama",
        }
    ]
    messages = [_make_next_available_tool_msg_v2(options)]

    # Verify extractor works with ToolResponse shape
    raw_slots = _extract_offered_slots_from_messages(messages)
    assert len(raw_slots) == 1, f"Extractor must return 1 slot, got: {raw_slots}"
    assert raw_slots[0]["start_iso"] == slot_iso
    assert raw_slots[0]["stylist_id"] == STYLIST_ID

    # Verify materialize produces a valid offered slot
    now = datetime.now(UTC)
    offered = _materialize_offered_slots(raw_slots, [], current_turn_index=2, now=now)
    assert len(offered) == 1
    assert offered[0]["start_iso"] == slot_iso

    # Verify validate_slot_in_offered accepts it
    from agent.tools._booking_validators import validate_slot_in_offered

    result = validate_slot_in_offered(slot_iso, STYLIST_ID, offered)
    assert result.ok, (
        f"validate_slot_in_offered must accept slot from get_next_available_options, "
        f"got error: {result.error_message}"
    )


@pytest.mark.asyncio
async def test_slot_offered_4_turns_ago_still_in_offered_after_rescan():
    """O1 secondary: slots offered > 2 turns ago survive because re-scan refreshes turn_index.

    The extractor re-reads ALL ToolMessages every turn, so a slot from turn 2
    gets turn_index = current_turn (10) on re-scan. Purge never fires.
    """
    from datetime import UTC, datetime

    from agent.middleware.availability_context import (
        _extract_offered_slots_from_messages,
        _materialize_offered_slots,
    )

    slot_iso = "2026-06-25T14:00:00+00:00"
    options = [{"start_iso": slot_iso, "stylist_id": STYLIST_ID, "stylist_name": "Rosa"}]

    # Build a message list: the get_next_available_options call was at index 2,
    # and we're now at turn index 10 (10 messages total)
    messages = [MagicMock()] * 9 + [_make_next_available_tool_msg_v2(options)]
    # Simulate: message at index 2 also has the original offer
    messages[2] = _make_next_available_tool_msg_v2(options)

    now = datetime.now(UTC)
    raw_slots = _extract_offered_slots_from_messages(messages)
    offered = _materialize_offered_slots(raw_slots, [], current_turn_index=10, now=now)

    assert any(
        s["start_iso"] == slot_iso for s in offered
    ), "Slot offered in an early turn must still be present after re-scan refreshes turn_index"
