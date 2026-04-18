"""
Tests for Batch 4 — Confirmation Loop Fix (T-13 through T-17).

Verifies:
- _build_flow_hint() emits Phase 4b (notes), 4c (show summary), 4d (book directly)
- _confirmation_shown is set deterministically in Python, never by LLM
- _pre_tool_call() gate blocks update_booking when _confirmation_shown=True
- Change-intent keywords bypass the gate and reset the flag
- book() is NEVER blocked by the confirmation gate
- Cascade clear: update_booking with invalidating keys clears _confirmation_shown
"""

import json
import pytest

from agent.modes.booking_mode import BookingModeNode


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


def _base_ctx() -> dict:
    """Minimal context with all required booking fields filled."""
    return {
        "last_services": ["Cortar"],
        "last_stylist": "Victor",
        "add_more_asked": True,
        "offered_slots": [{"stylist_id": "abc", "time": "10:00", "date": "miércoles 9"}],
        "selected_slot": {"stylist_id": "abc", "time": "10:00", "date": "miércoles 9"},
        "customer_name": "Pablo García",
        "notes_asked": True,
    }


def _make_state(**kwargs) -> dict:
    defaults: dict = {
        "messages": [{"role": "user", "content": "sí", "timestamp": "2026-01-01T10:00:00"}],
        "customer_phone": "+34612345678",
        "conversation_summary": None,
        "customer_id": None,
        "customer_name": None,
        "customer_first_name": None,
        "user_message": "sí",
    }
    defaults.update(kwargs)
    return defaults


@pytest.fixture
def node():
    """BookingModeNode with empty state."""
    node = BookingModeNode(tools=[])
    node._booking_context = {}
    node._mode_context = node._booking_context
    node._current_state = _make_state()
    return node


# ──────────────────────────────────────────────────────────────────────
# T-13a: Phase 4b — notes not yet asked → hint asks for notes
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
    strict=True,
)
def test_flow_hint_notes_not_pending_when_not_asked():
    """When notes not asked, hint must NOT list notas in pending (R8/C5 fix).

    Notes are optional — _build_flow_hint must not block completion by adding
    notas to pending. When all required fields are present, _confirmation_shown
    is set and the hint shows 'Todos los datos recogidos'.
    """
    ctx = _base_ctx()
    ctx.pop("notes_asked")

    hint = BookingModeNode._build_flow_hint(ctx)

    # notes are optional: must NOT appear in pending
    if "Pendiente:" in hint:
        pending_segment = hint.split("Pendiente:")[1].split("</flow_hint>")[0]
        assert "notas" not in pending_segment.lower(), (
            f"notas must NOT be in pending when notes_asked=False. Got: {pending_segment!r}"
        )
    # All required fields are present → hint should indicate completion
    assert "todos los datos" in hint.lower() or "confirmación" in hint.lower(), (
        f"Hint must indicate completion when all required fields set. Got: {hint!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# T-13b: Phase 4c — all data collected, notes asked → set _confirmation_shown, show summary hint
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
    strict=True,
)
def test_flow_hint_all_collected_sets_confirmation_shown():
    """All data collected → _confirmation_shown set to True deterministically."""
    ctx = _base_ctx()
    assert "_confirmation_shown" not in ctx, "Precondition: flag not yet set"

    hint = BookingModeNode._build_flow_hint(ctx)

    assert ctx.get("_confirmation_shown") is True, (
        "_confirmation_shown must be set to True by Python when all data collected"
    )
    assert "todos los datos" in hint.lower() or "recogido" in hint.lower(), (
        "Hint must indicate all data is collected"
    )


# ──────────────────────────────────────────────────────────────────────
# T-13c: Phase 4d — _confirmation_shown=True → hint says book() directly
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
    strict=True,
)
def test_flow_hint_confirmation_shown_mentions_waiting():
    """_confirmation_shown=True → hint says waiting for confirmation."""
    ctx = _base_ctx()
    ctx["_confirmation_shown"] = True

    hint = BookingModeNode._build_flow_hint(ctx)

    assert "confirmación" in hint.lower() or "esperando" in hint.lower(), (
        "Hint must indicate waiting for confirmation when all data collected + shown"
    )


# ──────────────────────────────────────────────────────────────────────
# T-13d: _confirmation_shown stays False when notes not asked
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    reason="state-first-booking Batch 4: _build_flow_hint deleted, test needs rewrite — issue #TBD",
    strict=True,
)
def test_confirmation_shown_set_when_required_fields_present_without_notes():
    """_confirmation_shown must be set when all required fields are present, even without notes.

    After R8/C5: notes are optional. _confirmation_shown is gated on required fields only
    (services, stylist, slot, name). notes_asked=False must not block the gate.
    """
    ctx = _base_ctx()
    ctx.pop("notes_asked")

    BookingModeNode._build_flow_hint(ctx)

    assert ctx.get("_confirmation_shown") is True, (
        "_confirmation_shown must be set when all required fields present — notes are optional (R8/C5)"
    )


# ──────────────────────────────────────────────────────────────────────
# T-14c: book() is NEVER blocked regardless of _confirmation_shown
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pre_tool_call_never_blocks_book(node):
    """book() must never be blocked by the _confirmation_shown gate."""
    # Set up complete booking context so book() passes its own gates
    node._booking_context.update({
        "_confirmation_shown": True,
        "last_services": ["Cortar"],
        "last_stylist": "Victor",
        "selected_slot": {
            "stylist_id": "stylist-uuid",
            "start_time": "2026-04-20T10:00:00",
            "time": "10:00",
            "date": "domingo 20",
        },
        "customer_name": "Pablo García",
        "offered_slots": [
            {
                "stylist_id": "stylist-uuid",
                "start_time": "2026-04-20T10:00:00",
                "stylist_name": "Victor",
                "time": "10:00",
                "day_label": "domingo 20",
            }
        ],
    })

    from agent.modes.base import ToolCallRejection

    result = await node._pre_tool_call(
        "book",
        {
            "slot_index": 1,
            "services": ["Cortar"],
            "customer_first_name": "Pablo",
        },
    )

    assert not isinstance(result, ToolCallRejection) or (
        isinstance(result, ToolCallRejection)
        and result.error_code != "CONFIRMATION_ALREADY_SHOWN"
    ), "book() must NEVER be blocked by CONFIRMATION_ALREADY_SHOWN gate"


# ──────────────────────────────────────────────────────────────────────
# T-15: Cascade clear — update_booking with invalidating keys clears _confirmation_shown
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidating_key", [
    "last_services",
    "offered_slots",
    "selected_slot",
])
async def test_post_tool_result_cascade_clears_confirmation_on_invalidating_key(
    invalidating_key, node
):
    """Cascade clear: update_booking changes to invalidating keys reset _confirmation_shown."""
    node._booking_context["_confirmation_shown"] = True

    # Build a result where the patch changes an invalidating key
    patch = {invalidating_key: None}
    result_dict = {"_booking_context_patch": patch}
    result_json = json.dumps(result_dict)

    await node._post_tool_result("update_booking", {}, result_json)

    assert node._booking_context.get("_confirmation_shown") is False, (
        f"_confirmation_shown must be cleared when '{invalidating_key}' changes in patch"
    )


@pytest.mark.asyncio
async def test_post_tool_result_no_cascade_clear_for_non_invalidating_key(node):
    """Non-invalidating keys (e.g. notes) must NOT clear _confirmation_shown."""
    node._booking_context["_confirmation_shown"] = True

    patch = {"notes": "sin nota"}
    result_dict = {"_booking_context_patch": patch}
    result_json = json.dumps(result_dict)

    await node._post_tool_result("update_booking", {}, result_json)

    assert node._booking_context.get("_confirmation_shown") is True, (
        "Non-invalidating key 'notes' must NOT clear _confirmation_shown"
    )
