"""Top-level graph factory — Phase 7.

create_graph(checkpointer, llm_factory, store) → CompiledStateGraph

Topology:
  START → preprocess → router → {general | booking} → END

  preprocess returns Command(goto="router")
  router returns Command(goto="general"|"booking")
  general/booking return plain dicts → default edge to END

Routing is fully Command-driven; no static conditional edges are needed.
The only static edges are general→END and booking→END so LangGraph can
infer the graph termination path.

store: accepted for interface compat with main.py; AsyncRedisStore wiring
is deferred post-MVP.
"""

from __future__ import annotations

from typing import Any

from langgraph.constants import END
from langgraph.graph import StateGraph

from agent.llm import get_llm
from agent.state import AgentState


def create_graph(
    checkpointer: Any = None,
    llm_factory: Any = None,
    store: Any = None,
) -> Any:
    """Build and compile the top-level conversation graph.

    Args:
        checkpointer: Optional LangGraph checkpointer (AsyncRedisSaver / MemorySaver).
        llm_factory: Zero-arg callable → BaseChatModel.  Defaults to get_llm().
        store: Accepted for compat; AsyncRedisStore wiring deferred post-MVP.

    Returns:
        CompiledStateGraph
    """
    # Lazy imports — keeps module-load fast; avoids circular imports at package init
    from agent.booking.subgraph import build_booking_subgraph
    from agent.nodes.general import build_general_node
    from agent.nodes.preprocess import preprocess_node
    from agent.nodes.router import router_node

    _llm_factory = llm_factory if llm_factory is not None else (lambda: get_llm())

    # Build child subgraphs
    booking_subgraph = build_booking_subgraph(llm_factory=_llm_factory)
    general_node = build_general_node(llm_factory=_llm_factory)

    builder = StateGraph(AgentState)

    # Nodes
    builder.add_node("preprocess", preprocess_node)
    builder.add_node("router", router_node)
    builder.add_node("general", general_node)
    builder.add_node("booking", booking_subgraph)

    # Entry point
    builder.set_entry_point("preprocess")

    # Terminal static edges (Command(goto=...) from router drives dynamic routing)
    builder.add_edge("general", END)
    builder.add_edge("booking", END)

    return builder.compile(checkpointer=checkpointer)
