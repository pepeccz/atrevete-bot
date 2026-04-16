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


def test_flow_hint_phase_4b_notes_not_asked():
    """Phase 4b: all data collected except notes → hint asks for notes."""
    ctx = _base_ctx()
    ctx.pop("notes_asked")  # notes not yet asked

    hint = BookingModeNode._build_flow_hint(ctx)

    assert "Paso 5" in hint or "nota" in hint.lower(), (
        "Hint must mention notes (Paso 5) when notes_asked is False"
    )
    # The hint may mention "resumen" in negation ("no muestres resumen") — that's fine.
    # What matters is it doesn't say to SHOW the summary.
    assert "mostrá el resumen" not in hint.lower(), (
        "Hint must NOT instruct to show summary before notes are asked"
    )


# ──────────────────────────────────────────────────────────────────────
# T-13b: Phase 4c — all data collected, notes asked → set _confirmation_shown, show summary hint
# ──────────────────────────────────────────────────────────────────────


def test_flow_hint_phase_4c_sets_confirmation_shown():
    """Phase 4c: all data + notes asked → _confirmation_shown set to True."""
    ctx = _base_ctx()
    assert "_confirmation_shown" not in ctx, "Precondition: flag not yet set"

    hint = BookingModeNode._build_flow_hint(ctx)

    assert ctx.get("_confirmation_shown") is True, (
        "_confirmation_shown must be set to True by Python in Phase 4c"
    )
    assert "resumen" in hint.lower() or "confirmo" in hint.lower(), (
        "Hint must tell LLM to show summary and ask ¿Te confirmo?"
    )


# ──────────────────────────────────────────────────────────────────────
# T-13c: Phase 4d — _confirmation_shown=True → hint says book() directly
# ──────────────────────────────────────────────────────────────────────


def test_flow_hint_phase_4d_confirmation_already_shown():
    """Phase 4d: _confirmation_shown=True → hint says call book() DIRECTLY."""
    ctx = _base_ctx()
    ctx["_confirmation_shown"] = True

    hint = BookingModeNode._build_flow_hint(ctx)

    assert "book()" in hint, "Hint must reference book() in Phase 4d"
    assert "DIRECTAMENTE" in hint or "directamente" in hint.lower(), (
        "Hint must emphasize calling book() directly"
    )
    assert "update_booking" not in hint.lower() or "NO" in hint or "no" in hint.lower(), (
        "Hint must discourage update_booking when confirmation shown"
    )


# ──────────────────────────────────────────────────────────────────────
# T-13d: _confirmation_shown stays False when notes not asked
# ──────────────────────────────────────────────────────────────────────


def test_confirmation_shown_not_set_when_notes_missing():
    """_confirmation_shown must NOT be set if notes have not been asked."""
    ctx = _base_ctx()
    ctx.pop("notes_asked")

    BookingModeNode._build_flow_hint(ctx)

    assert not ctx.get("_confirmation_shown"), (
        "_confirmation_shown must stay False when notes not yet asked"
    )


# ──────────────────────────────────────────────────────────────────────
# T-14a: _pre_tool_call blocks update_booking when _confirmation_shown=True (no change-intent)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pre_tool_call_blocks_update_booking_after_confirmation(node):
    """Gate blocks update_booking when _confirmation_shown=True and no change-intent."""
    node._booking_context["_confirmation_shown"] = True
    node._current_state = _make_state(user_message="sí")
    # Simulate the messages list reflects "sí" (affirmative — no change-intent)
    node._current_state["messages"] = [
        {"role": "user", "content": "sí", "timestamp": "2026-01-01T10:00:00"}
    ]
    node._current_state["user_message"] = "sí"

    from agent.modes.base import ToolCallRejection

    result = await node._pre_tool_call("update_booking", {"notes": "nada"})

    assert isinstance(result, ToolCallRejection), (
        "update_booking must be rejected when _confirmation_shown=True without change-intent"
    )
    assert result.error_code == "CONFIRMATION_ALREADY_SHOWN"


# ──────────────────────────────────────────────────────────────────────
# T-14b: change-intent keyword allows update_booking and resets flag
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("user_message", [
    "quiero cambiar la estilista",
    "mejor con Pilar",
    "en realidad prefiero el jueves",
    "no, otro día",
    "modificar la fecha",
    "espera, cambiar servicio",
])
async def test_pre_tool_call_allows_update_booking_with_change_intent(user_message, node):
    """Change-intent keywords allow update_booking and reset _confirmation_shown."""
    node._booking_context["_confirmation_shown"] = True
    node._current_state = _make_state(user_message=user_message)
    node._current_state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-01-01T10:00:00"}
    ]
    node._current_state["user_message"] = user_message

    from agent.modes.base import ToolCallRejection

    result = await node._pre_tool_call("update_booking", {"stylist_name": "Pilar"})

    assert not isinstance(result, ToolCallRejection), (
        f"update_booking must be ALLOWED when user says '{user_message}'"
    )
    assert node._booking_context.get("_confirmation_shown") is False, (
        "Change-intent must reset _confirmation_shown to False"
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
