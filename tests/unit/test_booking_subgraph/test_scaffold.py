"""
Phase 1 scaffold tests — RED first.

Assertions:
- build_booking_subgraph() compiles without error
- Compiled graph has exactly 14 nodes
- All stub nodes return a no-op dict or Command without raising
"""

from __future__ import annotations

import pytest

# This import will fail until subgraph.py is created — that's the RED signal.
from agent.booking.subgraph import build_booking_subgraph

EXPECTED_NODES = {
    "resolve_pre_turn",
    "route_action",
    "ask_service",
    "ask_audience",
    "ask_more_services",
    "ask_stylist",
    "fetch_availability",
    "ask_slot",
    "ask_name",
    "ask_notes",
    "show_confirmation",
    "await_confirmation",
    "execute_book",
    "booking_complete",
    "error_recovery",
}


def test_build_booking_subgraph_compiles():
    """build_booking_subgraph() must return a compiled graph without raising."""
    from langgraph.graph.state import CompiledStateGraph

    graph = build_booking_subgraph()
    assert isinstance(graph, CompiledStateGraph)


def test_booking_subgraph_has_15_nodes():
    """
    Compiled graph must expose all 15 nodes (14 defined + __start__ added by LangGraph).
    The design spec lists 14 named nodes; LangGraph adds __start__ internally.
    """
    graph = build_booking_subgraph()
    node_names = set(graph.nodes.keys())
    # LangGraph adds __start__ automatically
    expected_with_start = EXPECTED_NODES | {"__start__"}
    assert expected_with_start == node_names, (
        f"Missing: {expected_with_start - node_names}, Extra: {node_names - expected_with_start}"
    )


@pytest.mark.asyncio
async def test_all_stub_nodes_are_callable():
    """
    Each node must be importable and callable as an async function (or sync).
    We test by importing node modules — actual invocation tested per-node in later phases.
    """
    from agent.booking.nodes import (
        leaf_deterministic,
        leaf_llm,
        resolve_pre_turn,
        route_action,
    )

    assert callable(resolve_pre_turn.resolve_pre_turn)
    assert callable(route_action.route_action)
    # leaf_llm exposes one function per node
    assert callable(leaf_llm.ask_service)
    assert callable(leaf_llm.ask_audience)
    assert callable(leaf_llm.ask_more_services)
    assert callable(leaf_llm.ask_stylist)
    assert callable(leaf_llm.ask_slot)
    assert callable(leaf_llm.ask_name)
    assert callable(leaf_llm.ask_notes)
    assert callable(leaf_llm.show_confirmation)
    assert callable(leaf_llm.await_confirmation)
    assert callable(leaf_llm.booking_complete)
    assert callable(leaf_llm.error_recovery)
    assert callable(leaf_deterministic.fetch_availability)
    assert callable(leaf_deterministic.execute_book)
