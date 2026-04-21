"""
Booking subgraph — deterministic StateGraph.

Replaces BookingModeNode's LLM-agent-loop with a deterministic control flow.
LLM is confined to text-generation leaf nodes (one call, zero tools per turn).

Design ref: design §Architecture Decisions D1–D8.
"""

from __future__ import annotations

from langgraph.graph import StateGraph

from agent.booking.nodes.leaf_deterministic import execute_book, fetch_availability
from agent.booking.nodes.leaf_llm import (
    ask_audience,
    ask_more_services,
    ask_name,
    ask_notes,
    ask_service,
    ask_slot,
    ask_stylist,
    await_confirmation,
    booking_complete,
    error_recovery,
    show_confirmation,
)
from agent.booking.nodes.escape_gate import escape_gate
from agent.booking.nodes.interpret_user_update import interpret_user_update
from agent.booking.nodes.reconcile_invalidations import reconcile_invalidations
from agent.booking.nodes.resolve_pre_turn import resolve_pre_turn
from agent.booking.nodes.route_action import route_action
from agent.state.schemas import ConversationState


def build_booking_subgraph():
    """
    Build and compile the booking deterministic subgraph.

    Entry: resolve_pre_turn (runs every turn, applies all resolvers).
    Routing: route_action (pure 13-branch FSM, returns Command(goto=LABEL)).
    LLM leaf nodes: ask_*, show_confirmation, await_confirmation, booking_complete, error_recovery.
    Deterministic nodes: fetch_availability, execute_book (loop back to route_action).

    Returns:
        Compiled LangGraph StateGraph ready to be mounted as a node in conversation_flow.
    """
    builder = StateGraph(ConversationState)

    # New entry pipeline (Phase 1 scaffolding)
    builder.add_node("escape_gate", escape_gate)
    builder.add_node("interpret_user_update", interpret_user_update)
    builder.add_node("reconcile_invalidations", reconcile_invalidations)

    # Legacy node — kept but bypassed until Phase 7 cleanup
    builder.add_node("resolve_pre_turn", resolve_pre_turn)

    # Router — pure FSM, no I/O
    builder.add_node("route_action", route_action)

    # LLM leaf nodes — each emits one AIMessage then END
    builder.add_node("ask_service", ask_service)
    builder.add_node("ask_audience", ask_audience)
    builder.add_node("ask_more_services", ask_more_services)
    builder.add_node("ask_stylist", ask_stylist)
    builder.add_node("ask_slot", ask_slot)
    builder.add_node("ask_name", ask_name)
    builder.add_node("ask_notes", ask_notes)
    builder.add_node("show_confirmation", show_confirmation)
    builder.add_node("await_confirmation", await_confirmation)
    builder.add_node("booking_complete", booking_complete)
    builder.add_node("error_recovery", error_recovery)

    # Deterministic action nodes — patch state, loop back to route_action
    builder.add_node("fetch_availability", fetch_availability)
    builder.add_node("execute_book", execute_book)

    # Entry edge — Phase 1: escape_gate → interpret_user_update → reconcile_invalidations → route_action
    # resolve_pre_turn is bypassed (kept until Phase 7 cleanup)
    builder.set_entry_point("escape_gate")
    builder.add_edge("escape_gate", "interpret_user_update")
    builder.add_edge("interpret_user_update", "reconcile_invalidations")
    builder.add_edge("reconcile_invalidations", "route_action")

    # route_action uses Command(goto=LABEL) — no explicit conditional edges needed.
    # LangGraph resolves Command destinations automatically.

    return builder.compile()
