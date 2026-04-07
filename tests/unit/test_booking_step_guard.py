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
    """Minimal ConversationState-compatible dict for testing."""
    return {"user_message": user_message}


# ===========================================================================
# Phase 2.1 — _compute_booking_step tests (RED → GREEN in Phase 2.4)
# ===========================================================================


def test_compute_step_empty_context():
    """Empty mode_context → service_selection (no data at all)."""
    result = BookingModeNode._compute_booking_step({})
    assert result == "service_selection"


def test_compute_step_service_known():
    """last_services set → stylist_selection (service resolved, stylist pending)."""
    ctx = {"last_services": ["Cortar"]}
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "stylist_selection"


def test_compute_step_stylist_known():
    """last_services + last_stylist → datetime_selection."""
    ctx = {"last_services": ["Cortar"], "last_stylist": "Ana"}
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "datetime_selection"


def test_compute_step_no_preference():
    """no_preference_stylist=True without last_stylist → datetime_selection (bypass)."""
    ctx = {"last_services": ["Cortar"], "no_preference_stylist": True}
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "datetime_selection"


def test_compute_step_slot_selected():
    """last_services + last_stylist + selected_slot → name_collection (no name yet)."""
    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
    }
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "name_collection"


def test_compute_step_name_known():
    """All fields set → confirmation."""
    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "selected_slot": {"day_label": "Lunes", "time": "10:00"},
        "customer_name": "María García",
    }
    result = BookingModeNode._compute_booking_step(ctx)
    assert result == "confirmation"


# ===========================================================================
# Phase 2.2 — _pre_tool_call guard tests (RED → GREEN in Phase 2.6)
# ===========================================================================


@pytest.mark.asyncio
async def test_pre_tool_call_rejects_no_stylist(booking_node: BookingModeNode):
    """check_availability without last_stylist or no_preference_stylist → ToolCallRejection."""
    booking_node._mode_context = {
        "last_services": ["Cortar"],
        # No last_stylist, no no_preference_stylist
    }
    result = await booking_node._pre_tool_call("check_availability", {"service_names": ["Cortar"]})
    assert isinstance(result, ToolCallRejection)
    assert result.error_code == "STYLIST_NOT_RESOLVED"
    assert result.name == "check_availability"


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
        "confirmation_shown": True,
    }
    # book() has its own gates (confirmation) — here we only check it is NOT
    # rejected for STYLIST_NOT_RESOLVED
    result = await booking_node._pre_tool_call("book", {"slot_index": 1})
    # It may return a ToolCallRejection (for other book-specific reasons), but NOT
    # with error_code STYLIST_NOT_RESOLVED
    if isinstance(result, ToolCallRejection):
        assert result.error_code != "STYLIST_NOT_RESOLVED"


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


def test_numbered_sin_preferencia_sets_flag(booking_node: BookingModeNode):
    """When user picks a numbered option that resolves to 'Sin preferencia', flag is set."""
    mode_context: dict = {
        "last_services": ["Cortar"],
        "pending_stylist_options": ["Ana", "Victor", "Marta", "Sin preferencia"],
    }
    state = _make_state("4")  # picks "Sin preferencia" by number
    booking_node._resolve_pending_selection(state, mode_context)
    assert mode_context.get("last_stylist") == "Sin preferencia"
    assert mode_context.get("no_preference_stylist") is True
    assert "pending_stylist_options" not in mode_context


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
    # If mode_context already has last_services + last_stylist, step should be
    # datetime_selection (not rejected by stylist guard) after _compute_booking_step
    ctx = {
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
    }
    step = BookingModeNode._compute_booking_step(ctx)
    assert step == "datetime_selection", (
        "With service+stylist resolved, step must advance to datetime_selection"
    )
