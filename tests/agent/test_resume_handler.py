"""Tests for build_invoke_input resume handler — Task 7.2."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.types import Command

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(next_nodes: tuple[str, ...]) -> MagicMock:
    snap = MagicMock()
    snap.next = next_nodes
    return snap


def _make_graph(snapshot: MagicMock) -> MagicMock:
    graph = MagicMock()
    graph.aget_state = AsyncMock(return_value=snapshot)
    return graph


# ---------------------------------------------------------------------------
# 7.2.1  No interrupt — snapshot.next is empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_interrupt_returns_state_seed():
    """When snapshot.next is empty, return (state_seed, False)."""
    from agent.resume_handler import build_invoke_input

    snapshot = _make_snapshot(())
    graph = _make_graph(snapshot)
    config = {"configurable": {"thread_id": "c1"}}
    state_seed = {"conversation_id": "c1", "user_message": "hola"}

    payload, interrupted = await build_invoke_input(graph, config, "hola", state_seed)

    assert interrupted is False
    assert payload is state_seed


# ---------------------------------------------------------------------------
# 7.2.2  Interrupt at await_confirmation — must return Command(resume=...)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_await_confirmation_returns_command():
    """When snapshot.next contains 'await_confirmation', return (Command(resume=...), True)."""
    from agent.resume_handler import build_invoke_input

    snapshot = _make_snapshot(("await_confirmation",))
    graph = _make_graph(snapshot)
    config = {"configurable": {"thread_id": "c2"}}
    state_seed = {"conversation_id": "c2", "user_message": "sí"}

    payload, interrupted = await build_invoke_input(graph, config, "sí", state_seed)

    assert interrupted is True
    assert isinstance(payload, Command)
    assert payload.resume == "sí"


# ---------------------------------------------------------------------------
# 7.2.3  Interrupt at a NON-interrupt node (e.g. "router") — not an interrupt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_interrupt_node_not_treated_as_interrupt():
    """Nodes not in INTERRUPT_NODES should NOT trigger resume path."""
    from agent.resume_handler import build_invoke_input

    snapshot = _make_snapshot(("router",))
    graph = _make_graph(snapshot)
    config = {"configurable": {"thread_id": "c3"}}
    state_seed = {"conversation_id": "c3", "user_message": "test"}

    payload, interrupted = await build_invoke_input(graph, config, "test", state_seed)

    assert interrupted is False
    assert payload is state_seed


# ---------------------------------------------------------------------------
# 7.2.4  INTERRUPT_NODES set is exported and contains await_confirmation
# ---------------------------------------------------------------------------


def test_interrupt_nodes_set():
    """INTERRUPT_NODES must be importable and contain 'await_confirmation'."""
    from agent.resume_handler import INTERRUPT_NODES

    assert "await_confirmation" in INTERRUPT_NODES
