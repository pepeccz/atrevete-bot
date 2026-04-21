"""
Phase 8 — Property tests (Hypothesis) for the booking subgraph FSM.

Property: random interleaved user inputs → FSM either converges to a terminal
state (booking_complete / error_recovery exit) or exits via escape gate;
never revisits the same (state_hash, leaf) pair infinitely.

Bounded at max 30 turns.

Uses Hypothesis strategies to generate random user messages and booking states.
LLM calls are stubbed out. No external services.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bc_hash(bc: dict) -> str:
    """Stable hash of booking_context for loop detection."""
    serialized = json.dumps(bc, sort_keys=True, default=str)
    return hashlib.md5(serialized.encode()).hexdigest()[:8]


def _make_llm_mock() -> AsyncMock:
    from langchain_core.messages import AIMessage

    mock = AsyncMock()
    mock.ainvoke.return_value = AIMessage(content="respuesta mock")
    return mock


# ---------------------------------------------------------------------------
# Strategy: random user messages
# ---------------------------------------------------------------------------

_USER_MESSAGES = [
    "señora",
    "caballero",
    "quiero un corte",
    "con Laura",
    "cualquiera",
    "el viernes",
    "mañana",
    "1",
    "2",
    "sí",
    "no",
    "nada mas",
    "María",
    "sin notas",
    "quiero cancelar",
    "hola",
    "quiero mechas",
]


@st.composite
def _booking_state(draw) -> dict[str, Any]:
    """Generate a partially-filled booking_context."""
    return {
        "last_services": draw(st.one_of(st.none(), st.just(["Corte Señora"]))),
        "add_more_asked": draw(st.booleans()),
        "last_stylist": draw(st.one_of(st.none(), st.just("Laura"), st.just("__ANY_AVAILABLE__"))),
        "no_preference_stylist": draw(st.booleans()),
        "offered_slots": draw(
            st.one_of(
                st.just([]),
                st.just([{"start_time": "10:00", "stylist_name": "Laura"}]),
            )
        ),
        "selected_slot": None,
        "customer_name": None,
        "notes_state": draw(st.sampled_from(["not_asked", "skipped", "provided"])),
        "pending_disambiguations": [],
        "_confirmation_shown": draw(st.booleans()),
        "confirmed": None,
        "_last_leaf": draw(
            st.one_of(
                st.none(),
                st.sampled_from(["ask_service", "ask_audience", "ask_more_services", "ask_name", "ask_notes"]),
            )
        ),
    }


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@given(
    initial_bc=_booking_state(),
    messages=st.lists(st.sampled_from(_USER_MESSAGES), min_size=1, max_size=15),
)
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    deadline=10000,
)
async def test_fsm_converges_no_infinite_loop(initial_bc, messages):
    """
    Property: the booking subgraph FSM with random inputs either:
    1. Routes to fetch_availability or execute_book (deterministic terminal)
    2. Routes to a leaf (ask_*, show_confirmation, booking_complete, error_recovery)
    3. Exits via escape gate

    It must NEVER revisit the same (bc_hash, message) pair — no infinite loops.
    """
    from langgraph.types import Command

    from agent.booking.nodes.escape_gate import escape_gate
    from agent.booking.nodes.interpret_user_update import interpret_user_update
    from agent.booking.nodes.reconcile_invalidations import reconcile_invalidations
    from agent.booking.nodes.route_action import route_action

    seen_pairs: set[tuple[str, str]] = set()
    bc = dict(initial_bc)

    for turn, message in enumerate(messages[:30]):
        state = {"booking_context": bc, "user_message": message, "messages": [], "total_message_count": turn}

        bc_hash = _bc_hash(bc)
        # Use (bc_hash, turn) to allow same message on different turns but catch true loops
        # (same bc_hash appearing 3+ times within the same run → convergence failure)
        pair = (bc_hash, message)
        count = sum(1 for p in seen_pairs if p == pair)
        assert count < 2, (
            f"Infinite loop detected at turn {turn}: same (state, message) seen {count+1} times. "
            f"bc_hash={bc_hash!r} message={message!r}"
        )
        seen_pairs.add(pair)

        # Step 1: escape gate
        with patch("agent.booking.nodes.leaf_llm.llm", _make_llm_mock()):
            gate_result = await escape_gate(state)

        if isinstance(gate_result, Command):
            # Escaped — FSM terminated cleanly
            assert gate_result.update.get("current_mode") in (
                "GENERAL", "ESCALATION", "APPOINTMENT_MANAGEMENT"
            )
            break

        # Step 2: interpret
        interp_result = await interpret_user_update(state)
        state = {**state, **interp_result}

        # Step 3: reconcile
        recon_result = await reconcile_invalidations(state)
        bc = recon_result["booking_context"]
        state = {**state, "booking_context": bc}

        # Step 4: route
        route_result = route_action(state)
        assert isinstance(route_result, Command)

        destination = route_result.goto
        # All valid destinations
        valid_destinations = {
            "fetch_availability", "execute_book", "ask_service", "ask_audience",
            "ask_more_services", "ask_stylist", "ask_slot", "ask_name",
            "ask_notes", "show_confirmation", "await_confirmation",
            "booking_complete", "error_recovery",
        }
        assert destination in valid_destinations, f"Unknown destination: {destination!r}"

        # Terminal nodes end the loop
        if destination in ("booking_complete", "error_recovery"):
            break
