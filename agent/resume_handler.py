"""Interrupt resume handler — Phase 7.2.

build_invoke_input() inspects the current checkpoint snapshot and decides
whether to resume an interrupted subgraph or invoke normally.

Interrupt detection:
  - graph.aget_state(config) returns a StateSnapshot.
  - snapshot.next is a tuple of node names waiting to run.
  - If any node in snapshot.next is in INTERRUPT_NODES, the graph is paused
    at a human-in-the-loop interrupt and we must resume with Command(resume=...).

Usage in main.py:

    payload, interrupted = await build_invoke_input(
        graph, config, combined_text, state_seed
    )
    result = await graph.ainvoke(payload, config=config)
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

# Node names that use interrupt() and therefore require Command(resume=...) to continue
INTERRUPT_NODES: frozenset[str] = frozenset({"await_confirmation"})


async def build_invoke_input(
    graph: Any,
    config: dict,
    user_message: str,
    state_seed: dict,
) -> tuple[dict | Command, bool]:
    """Determine the correct payload to pass to graph.ainvoke().

    Args:
        graph: Compiled LangGraph StateGraph (must support aget_state).
        config: LangGraph run config (must contain configurable.thread_id).
        user_message: Raw user message text for this turn.
        state_seed: Full initial-state dict for a normal (non-resume) invocation.

    Returns:
        (payload, interrupted) where:
          - payload is Command(resume=user_message) if interrupted, else state_seed.
          - interrupted is True iff the graph is paused at an INTERRUPT_NODES node.
    """
    snapshot = await graph.aget_state(config)
    interrupted = bool(snapshot.next) and any(n in INTERRUPT_NODES for n in snapshot.next)

    if interrupted:
        return Command(resume=user_message), True

    return state_seed, False
