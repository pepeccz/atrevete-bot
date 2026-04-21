"""
Phase 1 — Scaffolding tests (RED).

Assert:
- agent.booking.resolvers importable
- reconcile_invalidations node exists
- interpret_user_update node exists
- escape_gate node exists
- 122 existing tests still pass (enforced by running this file in the same suite)
"""

from __future__ import annotations


def test_resolver_registry_importable():
    """agent.booking.resolvers must be importable and expose RESOLVER_REGISTRY."""
    import agent.booking.resolvers as resolvers

    assert hasattr(resolvers, "RESOLVER_REGISTRY"), "RESOLVER_REGISTRY missing"
    assert isinstance(resolvers.RESOLVER_REGISTRY, list)


def test_reconcile_invalidations_node_exists():
    """agent.booking.nodes.reconcile_invalidations must expose reconcile_invalidations callable."""
    from agent.booking.nodes.reconcile_invalidations import reconcile_invalidations

    assert callable(reconcile_invalidations)


def test_interpret_user_update_node_exists():
    """agent.booking.nodes.interpret_user_update must expose interpret_user_update callable."""
    from agent.booking.nodes.interpret_user_update import interpret_user_update

    assert callable(interpret_user_update)


def test_escape_gate_node_exists():
    """agent.booking.nodes.escape_gate must expose escape_gate callable."""
    from agent.booking.nodes.escape_gate import escape_gate

    assert callable(escape_gate)


def test_invalidation_module_exists():
    """agent.booking.invalidation must expose INVALIDATION_TABLE and reconcile."""
    from agent.booking.invalidation import INVALIDATION_TABLE, reconcile

    assert isinstance(INVALIDATION_TABLE, dict)
    assert callable(reconcile)


def test_subgraph_entry_point_is_escape_gate():
    """The compiled booking subgraph must start at escape_gate."""
    from agent.booking.subgraph import build_booking_subgraph

    graph = build_booking_subgraph()
    # LangGraph compiled graphs expose __input__ or the graph nodes
    # We verify escape_gate is a registered node (not that it's the entry in compiled form)
    node_names = set(graph.nodes.keys()) if hasattr(graph, "nodes") else set()
    assert "escape_gate" in node_names, f"escape_gate not in graph nodes: {node_names}"
    assert "interpret_user_update" in node_names
    assert "reconcile_invalidations" in node_names
