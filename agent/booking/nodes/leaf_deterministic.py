"""
Deterministic leaf nodes — Stubs (Phase 1 scaffolding).

fetch_availability and execute_book call services directly from booking_context.
Implementation in Phase 4.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command


async def fetch_availability(state: dict[str, Any]) -> Command:
    """No-op stub. Phase 4 will implement direct availability_service call."""
    return Command(goto="route_action")


async def execute_book(state: dict[str, Any]) -> Command:
    """No-op stub. Phase 4 will implement booking transaction."""
    return Command(goto="route_action")
