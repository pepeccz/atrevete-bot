"""
LLM leaf nodes — Stubs (Phase 1 scaffolding).

Each node loads a per-node prompt and calls llm.ainvoke() with zero tools.
Implementation in Phase 5.
"""

from __future__ import annotations

from typing import Any


async def ask_service(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def ask_audience(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def ask_more_services(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def ask_stylist(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def ask_slot(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def ask_name(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def ask_notes(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def show_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def await_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def booking_complete(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}


async def error_recovery(state: dict[str, Any]) -> dict[str, Any]:
    """No-op stub."""
    return {}
