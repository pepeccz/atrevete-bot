"""
route_action — Stub node (Phase 1 scaffolding).

Pure deterministic FSM router. Promoted from compute_next_prompt.
Implementation in Phase 3.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command


def route_action(state: dict[str, Any]) -> Command:
    """No-op stub. Phase 3 will implement 13-branch FSM."""
    return Command(goto="error_recovery")
