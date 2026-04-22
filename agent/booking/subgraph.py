"""Booking subgraph — Phase 5.11.

Compiles the booking FSM as a LangGraph StateGraph.

Graph layout (per-turn — subgraph processes ONE step per invocation):
  START → interpret_user_update (resolvers, no LLM)
       → escape_gate           (routes cancel/start_over/change_* or pass-through)
       → route_next            (dispatcher node: maps booking.step → leaf)
       → ONE of:
           ask_service | ask_audience | ask_stylist | ask_date
           | fetch_availability (→ ask_slot) | ask_slot
           | ask_name | ask_notes | await_confirmation (interrupt) | END

Leaf behavior:
  - LLM-call path: leaf emits AIMessage, returns Command(goto=END) — stops subgraph,
    waits for next user message in parent graph.
  - Fast-path (field already set): leaf returns Command(goto="route_next") — advances
    one more step in the same invocation without user input.

fetch_availability: on success → Command(goto="ask_slot"); on failure → Command(goto=END).
execute_book: always → Command(goto=END).
await_confirmation: uses interrupt() to pause; on resume routes to execute_book or route_next.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langgraph.graph import START, StateGraph

from agent.booking.actions import execute_book_node, fetch_availability_node
from agent.booking.await_confirmation import await_confirmation
from agent.booking.escape_gate import escape_gate
from agent.booking.interpret_user_update import interpret_user_update
from agent.booking.leaves import (
    ask_audience,
    ask_date,
    ask_more_services,
    ask_name,
    ask_notes,
    ask_service,
    ask_slot,
    ask_stylist,
)
from agent.booking.route_next import route_next
from agent.state import AgentState

logger = logging.getLogger(__name__)

# Node names
_INTERPRET = "interpret_user_update"
_ESCAPE = "escape_gate"
_ROUTE = "route_next"
_ASK_SERVICE = "ask_service"
_ASK_AUDIENCE = "ask_audience"
_ASK_MORE_SERVICES = "ask_more_services"
_ASK_STYLIST = "ask_stylist"
_ASK_DATE = "ask_date"
_FETCH_AVAIL = "fetch_availability"
_ASK_SLOT = "ask_slot"
_ASK_NAME = "ask_name"
_ASK_NOTES = "ask_notes"
_AWAIT_CONFIRM = "await_confirmation"
_EXECUTE_BOOK = "execute_book"


def build_booking_subgraph(
    llm_factory: Callable | None = None,
    checkpointer=None,
) -> Any:
    """Compile and return the booking FSM subgraph.

    Args:
        llm_factory: Optional callable returning a ChatOpenAI instance.
                     If provided, patches `agent.booking.leaves.get_llm`.
        checkpointer: Optional LangGraph checkpointer (InMemorySaver / AsyncRedisSaver).

    Returns:
        CompiledStateGraph
    """
    if llm_factory is not None:
        import agent.booking.leaves as _leaves

        _leaves.get_llm = llm_factory

    builder = StateGraph(AgentState)

    # --- Nodes ---
    builder.add_node(_INTERPRET, interpret_user_update)
    builder.add_node(_ESCAPE, escape_gate)
    builder.add_node(_ROUTE, _route_next_node)
    builder.add_node(_ASK_SERVICE, ask_service)
    builder.add_node(_ASK_AUDIENCE, ask_audience)
    builder.add_node(_ASK_MORE_SERVICES, ask_more_services)
    builder.add_node(_ASK_STYLIST, ask_stylist)
    builder.add_node(_ASK_DATE, ask_date)
    builder.add_node(_FETCH_AVAIL, fetch_availability_node)
    builder.add_node(_ASK_SLOT, ask_slot)
    builder.add_node(_ASK_NAME, ask_name)
    builder.add_node(_ASK_NOTES, ask_notes)
    builder.add_node(_AWAIT_CONFIRM, await_confirmation)
    builder.add_node(_EXECUTE_BOOK, execute_book_node)

    # --- Edges ---
    # START → interpret (all nodes use Command-based routing after this)
    builder.add_edge(START, _INTERPRET)

    # LangGraph 1.1.x: Command.goto overrides default edge, so we only need the
    # START edge. All other routing is done via Command objects returned from nodes.
    # No additional edges needed.

    return builder.compile(checkpointer=checkpointer)


async def _route_next_node(state: dict[str, Any]):
    """Wrapper node that calls route_next(state) and returns Command(goto=<node>)."""
    from langgraph.types import Command

    next_node = route_next(state)
    return Command(goto=next_node)
