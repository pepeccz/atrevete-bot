"""Interrupt resume handler — v2 (create_agent rewrite).

For the create_agent MVP, there are no HITL interrupts at the top-level graph.
build_invoke_input() always returns (state_seed, False).

The function signature is preserved so that agent/main.py requires no changes.
"""

from __future__ import annotations

from typing import Any


async def build_invoke_input(
    graph: Any,
    config: dict,
    user_message: str,
    state_seed: dict,
) -> tuple[dict, bool]:
    """Determine the correct payload to pass to graph.ainvoke().

    In the create_agent v2 architecture, there are no HITL interrupt nodes at
    the top-level graph — the agent handles confirmation in natural language.
    This function always returns (state_seed, False).

    Args:
        graph: Compiled LangGraph graph (unused in v2, kept for interface compat).
        config: LangGraph run config (unused in v2, kept for interface compat).
        user_message: Raw user message text (unused in v2, kept for interface compat).
        state_seed: Full initial-state dict for this invocation.

    Returns:
        (state_seed, False) — always a normal (non-resume) invocation.
    """
    return state_seed, False
