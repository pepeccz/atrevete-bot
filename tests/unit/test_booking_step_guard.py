"""Unit tests for BookingModeNode step computation, pre-tool guard, and sin-preferencia recognition.

Batch 2 of fix-booking-duplicate-and-step-skip:
  - _compute_booking_step() — pure function, 6 test cases
  - _pre_tool_call() guard for check_availability — 4 test cases
  - "sin preferencia" recognition — parametrized + edge cases
  - Atajo full-info bypass test
"""

from __future__ import annotations

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_mode import BookingModeNode


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def booking_node() -> BookingModeNode:
    """Create a bare BookingModeNode (no LLM needed for unit tests)."""
    return BookingModeNode(tools=[])


def _make_state(user_message: str = "") -> dict:
    """Minimal ConversationState-compatible dict for testing.

    Uses messages list (canonical channel) so get_last_user_message() works.
    The user_message field is cleared by preprocess_node before modes run.
    """
    messages = [{"role": "user", "content": user_message}] if user_message else []
    return {"messages": messages, "user_message": None}


# ===========================================================================
# Phase 2.1 — _compute_booking_step tests (RED → GREEN in Phase 2.4)
# ===========================================================================


def test_compute_step_empty_context():
    """Empty mode_context → service_selection (no data at all)."""
    result = BookingModeNode._compute_booking_step({})
    assert result == "service_selection"


def test_compute_step_service_known_no_add_more():
    """last_services set but add_more_asked=False → stays at service_selection."""
    ctx = {"last_services": ["Cortar"]}
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "service_selection"


def test_compute_step_service_known_add_more_asked():
    """last_services + add_more_asked → stylist_selection."""
    ctx = {"last_services": ["Cortar"], "add_more_asked": True}
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "stylist_selection"


def test_compute_step_stylist_known():
    """last_services + add_more_asked + last_stylist → datetime_selection."""
    ctx = {"last_services": ["Cortar"], "add_more_asked": True, "last_stylist": "Ana"}
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "datetime_selection"


def test_compute_step_no_preference():
    """no_preference_stylist=True without last_stylist → datetime_selection (bypass)."""
    ctx = {"last_services": ["Cortar"], "add_more_asked": True, "no_preference_stylist": True}
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "datetime_selection"


def test_compute_step_slot_selected():
    """last_services + last_stylist + selected_slot → name_collection (no name yet)."""
    ctx = {
        "last_services": ["Cortar"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
    }
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "name_collection"


def test_compute_step_name_known():
    """All fields set including notes_asked → confirmation."""
    ctx = {
        "last_services": ["Cortar"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
        "customer_name": "María García",
        "notes_asked": True,
    }
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "confirmation"


def test_compute_step_notes_not_asked():
    """All fields set but notes_asked=False → notes_collection."""
    ctx = {
        "last_services": ["Cortar"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
        "customer_name": "María García",
        "notes_asked": False,
    }
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "notes_collection"


def test_compute_step_notes_asked_missing_key():
    """notes_asked not present → notes_collection (falsy check)."""
    ctx = {
        "last_services": ["Cortar"],
        "add_more_asked": True,
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
        "customer_name": "María García",
        # notes_asked absent → falsy
    }
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "notes_collection"


# ===========================================================================
# Phase 2.2 — _pre_tool_call guard tests (RED → GREEN in Phase 2.6)
# ===========================================================================


@pytest.mark.asyncio
async def test_pre_tool_call_allows_with_stylist(booking_node: BookingModeNode):
    """check_availability with last_stylist set → returns tool_args (not rejection)."""
    tool_args = {"service_names": ["Cortar"], "stylist_name": "Ana"}
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
    }
    result = await booking_node._pre_tool_call("check_availability", tool_args)
    assert not isinstance(result, ToolCallRejection)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_pre_tool_call_allows_with_no_preference(booking_node: BookingModeNode):
    """check_availability with no_preference_stylist=True → allowed (not rejected)."""
    tool_args = {"service_names": ["Cortar"]}
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "no_preference_stylist": True,
        "last_stylist": "Sin preferencia",
    }
    result = await booking_node._pre_tool_call("check_availability", tool_args)
    assert not isinstance(result, ToolCallRejection)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_pre_tool_call_other_tools_unaffected(booking_node: BookingModeNode):
    """book() tool call is never rejected by the stylist-guard (only check_availability is)."""
    # No stylist at all — but tool is "book", guard should not apply
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        # No last_stylist, no no_preference_stylist
    }
    # book() has its own gates (confirmation) — here we only check it is NOT
    # rejected for STYLIST_NOT_RESOLVED
    result = await booking_node._pre_tool_call("book", {"slot_index": 1})
    # It may return a ToolCallRejection (for other book-specific reasons), but NOT
    # with error_code STYLIST_NOT_RESOLVED
    if isinstance(result, ToolCallRejection):
        assert result.error_code != "STYLIST_NOT_RESOLVED"


# ===========================================================================
# Batch 1 — STYLIST_NOT_RESOLVED deadlock fix (stylist_name from tool_args)
# ===========================================================================


@pytest.mark.asyncio
async def test_pre_tool_call_allows_stylist_name_in_args(booking_node: BookingModeNode):
    """LLM provides stylist_name in tool_args → guard passes even with empty mode_context.

    Spec: Domain A — Scenario: LLM provides stylist_name in args — guard passes.
    """
    tool_args = {"service_names": ["Cortar"], "stylist_name": "Victor"}
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        # last_stylist NOT set, no_preference_stylist NOT set
    }
    result = await booking_node._pre_tool_call("check_availability", tool_args)
    assert not isinstance(result, ToolCallRejection), (
        "Guard must NOT reject when LLM provides stylist_name in tool_args"
    )
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_pre_tool_call_sets_last_stylist_from_args(booking_node: BookingModeNode):
    """stylist_name from tool_args is promoted to mode_context['last_stylist'].

    Spec: Domain A — _pre_tool_call must propagate stylist from args to context.
    """
    tool_args = {"service_names": ["Cortar"], "stylist_name": "Marta"}
    booking_node._mode_context = {
        "last_services": ["Cortar"],
    }
    await booking_node._pre_tool_call("check_availability", tool_args)
    assert booking_node._mode_context.get("last_stylist") == "Marta", (
        "last_stylist must be set from tool_args when previously absent"
    )


@pytest.mark.asyncio
async def test_pre_tool_call_does_not_overwrite_existing_last_stylist(
    booking_node: BookingModeNode,
):
    """If last_stylist already set, tool_args stylist_name does NOT overwrite it.

    Spec: Domain A — Scenario: last_stylist already set — guard passes (regression).
    """
    tool_args = {"service_names": ["Cortar"], "stylist_name": "Pilar"}
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        "last_stylist": "Harolyn",  # already set — must NOT be overwritten
    }
    result = await booking_node._pre_tool_call("check_availability", tool_args)
    assert not isinstance(result, ToolCallRejection)
    assert booking_node._mode_context.get("last_stylist") == "Harolyn", (
        "Existing last_stylist must NOT be overwritten by tool_args stylist_name"
    )


@pytest.mark.asyncio
async def test_pre_tool_call_allows_no_stylist_no_context(booking_node: BookingModeNode):
    """check_availability with service but no stylist info → allowed (guard removed).

    Change B: STYLIST_NOT_RESOLVED guard is gone — LLM decides when to call.
    """
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        # No last_stylist, no no_preference_stylist
    }
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"]}
    )
    assert not isinstance(result, ToolCallRejection)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_pre_tool_call_rejects_disambiguation_pending(booking_node: BookingModeNode):
    """_has_pending_disambiguation=True, no last_services → rejected (gate restored).

    Change A: DISAMBIGUATION_PENDING gate blocks check_availability when
    disambiguation questions are pending and services not yet resolved.
    """
    booking_node._mode_context = {
        "_has_pending_disambiguation": True,
        # No last_services
    }
    result = await booking_node._pre_tool_call(
        "check_availability", {"service_names": ["Cortar"]}
    )
    assert isinstance(result, ToolCallRejection)
    assert result.error_code == "DISAMBIGUATION_PENDING"


@pytest.mark.asyncio
async def test_pre_tool_call_empty_stylist_passes_through(booking_node: BookingModeNode):
    """stylist_name='' in tool_args → passes through (no longer rejected).

    Change B: Empty string is no longer treated as missing — guard removed.
    """
    tool_args = {"service_names": ["Cortar"], "stylist_name": ""}
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        # No last_stylist, no no_preference_stylist
    }
    result = await booking_node._pre_tool_call("check_availability", tool_args)
    assert not isinstance(result, ToolCallRejection)
    assert isinstance(result, dict)


# ===========================================================================
# Phase 2.3 — "Sin preferencia" recognition tests (RED → GREEN in Phase 2.5)
# ===========================================================================

_SIN_PREFERENCIA_PHRASES = [
    "sin preferencia",
    "me da igual",
    "cualquiera",
    "no tengo preferencia",
    "da lo mismo",
    "no me importa",
    "la que sea",
    "el que sea",
]


@pytest.mark.parametrize("phrase", _SIN_PREFERENCIA_PHRASES)
def test_sin_preferencia_phrases(booking_node: BookingModeNode, phrase: str):
    """All 8 recognized no-preference phrases set the flag and last_stylist."""
    mode_context: dict = {"last_services": ["Cortar"]}
    state = _make_state(phrase)
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context.get("no_preference_stylist") is True, (
        f"Expected no_preference_stylist=True for phrase {phrase!r}"
    )
    assert mode_context.get("last_stylist") == "Sin preferencia", (
        f"Expected last_stylist='Sin preferencia' for phrase {phrase!r}"
    )


def test_sin_preferencia_case_insensitive(booking_node: BookingModeNode):
    """Phrase in UPPERCASE is still recognized as no-preference."""
    mode_context: dict = {"last_services": ["Cortar"]}
    state = _make_state("ME DA IGUAL")
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context.get("no_preference_stylist") is True
    assert mode_context.get("last_stylist") == "Sin preferencia"


def test_unrecognized_phrase_no_flag(booking_node: BookingModeNode):
    """A message that doesn't match any pattern does NOT set the flag."""
    mode_context: dict = {"last_services": ["Cortar"]}
    state = _make_state("quiero a la mejor")
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context.get("no_preference_stylist") is None or (
        mode_context.get("no_preference_stylist") is False
    )
    assert mode_context.get("last_stylist") is None


# ===========================================================================
# Atajo test — full info in single message
# ===========================================================================


def test_full_info_atajo_reaches_slot_selection():
    """Single message with service+stylist+date → booking_step advances past stylist."""
    # With add_more_asked=True (auto-set by shortcut), service+stylist resolved →
    # datetime_selection
    ctx = {
        "last_services": ["Cortar"],
        "add_more_asked": True,
        "last_stylist": "Ana",
    }
    step = BookingModeNode._compute_booking_step(ctx)
    assert step == "datetime_selection", (
        "With service+stylist resolved + add_more_asked, step must advance to datetime_selection"
    )


# ===========================================================================
# Change C — _post_tool_result no_preference inference tests
# ===========================================================================


@pytest.mark.asyncio
async def test_post_tool_result_sets_no_preference_when_slots_and_no_stylist(
    booking_node: BookingModeNode,
):
    """No stylist_name in tool_args + result has slots → no_preference_stylist=True, last_stylist='Sin preferencia'."""
    booking_node._mode_context = {}
    tool_args = {"service_names": ["Cortar"]}  # No stylist_name
    result_dict = {"available_slots": [{"stylist_id": "abc", "start_time": "2026-04-15T10:00:00"}]}
    import json

    await booking_node._post_tool_result("check_availability", tool_args, json.dumps(result_dict))
    assert booking_node._mode_context.get("no_preference_stylist") is True
    assert booking_node._mode_context.get("last_stylist") == "Sin preferencia"


@pytest.mark.asyncio
async def test_post_tool_result_no_preference_not_set_when_stylist_named(
    booking_node: BookingModeNode,
):
    """stylist_name='Marta' in tool_args + slots → no_preference_stylist NOT set."""
    booking_node._mode_context = {}
    tool_args = {"service_names": ["Cortar"], "stylist_name": "Marta"}
    result_dict = {"available_slots": [{"stylist_id": "abc", "start_time": "2026-04-15T10:00:00"}]}
    import json

    await booking_node._post_tool_result("check_availability", tool_args, json.dumps(result_dict))
    assert not booking_node._mode_context.get("no_preference_stylist")


@pytest.mark.asyncio
async def test_post_tool_result_no_preference_not_set_when_empty_slots(
    booking_node: BookingModeNode,
):
    """No stylist_name + empty slots → no_preference_stylist NOT set."""
    booking_node._mode_context = {}
    tool_args = {"service_names": ["Cortar"]}  # No stylist_name
    result_dict = {"available_slots": []}
    import json

    await booking_node._post_tool_result("check_availability", tool_args, json.dumps(result_dict))
    assert not booking_node._mode_context.get("no_preference_stylist")
    assert booking_node._mode_context.get("last_stylist") is None


@pytest.mark.asyncio
async def test_post_tool_result_no_preference_does_not_overwrite_last_stylist(
    booking_node: BookingModeNode,
):
    """last_stylist='Ana' already set + no stylist_name + slots → no_preference=True but last_stylist stays 'Ana'."""
    booking_node._mode_context = {"last_stylist": "Ana"}
    tool_args = {"service_names": ["Cortar"]}  # No stylist_name
    result_dict = {"available_slots": [{"stylist_id": "abc", "start_time": "2026-04-15T10:00:00"}]}
    import json

    await booking_node._post_tool_result("check_availability", tool_args, json.dumps(result_dict))
    assert booking_node._mode_context.get("no_preference_stylist") is True
    assert booking_node._mode_context.get("last_stylist") == "Ana"
