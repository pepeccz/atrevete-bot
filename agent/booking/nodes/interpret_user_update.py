"""
interpret_user_update — Deterministic entity extraction node.

Runs all registered resolvers in fixed order on the incoming user message.
Returns a booking_context_patch and a user_action signal.

Design ref: design §D1, §D2, spec R1.1–R1.10, R4.2.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def interpret_user_update(state: dict[str, Any]) -> dict[str, Any]:
    """Run all resolvers in RESOLVER_REGISTRY order; emit patch + user_action.

    Returns:
        {
          "booking_context_patch": {"patch": {...}, "cleared": [...]},
          "user_action": "PROVIDE_FIELD" | "CHANGE_DATE" | "AFFIRM" | "NEGATE" | "UNKNOWN",
        }
    """
    from agent.booking.resolvers import RESOLVER_REGISTRY
    from agent.booking.resolvers.service import _load_catalog_from_cache_async

    user_text: str = state.get("user_message") or ""
    if not user_text:
        for msg in reversed(state.get("messages") or []):
            if msg.get("role") == "user":
                user_text = msg.get("content", "") or ""
                break
    bc: dict[str, Any] = dict(state.get("booking_context") or {})

    # Refresh the service resolver's catalog snapshot from the shared TTL
    # cache. Called here (async context) so the sync resolver path below can
    # read the latest rows without needing an event loop itself.
    try:
        await _load_catalog_from_cache_async()
    except Exception:  # noqa: BLE001 — fail-open, resolvers handle empty catalog
        logger.exception("interpret_user_update | catalog preload failed; continuing")

    merged_patch: dict[str, Any] = {}
    merged_cleared: list[str] = []
    derived_action: str = "UNKNOWN"

    for resolver_fn in RESOLVER_REGISTRY:
        try:
            result = resolver_fn(user_text, bc, state)
        except Exception:
            logger.exception("resolver %s raised; skipping", getattr(resolver_fn, "__name__", "?"))
            result = None

        if not result or not result.get("matched"):
            continue

        patch = result.get("patch") or {}
        cleared = result.get("cleared") or []
        action = result.get("user_action")

        merged_patch.update(patch)
        for k in cleared:
            if k not in merged_cleared:
                merged_cleared.append(k)

        if action and derived_action == "UNKNOWN":
            derived_action = action

    logger.info(
        "interpret_user_update | patch_keys=%s | cleared=%s | user_action=%s",
        sorted(merged_patch.keys()),
        merged_cleared,
        derived_action,
    )

    return {
        "booking_context_patch": {"patch": merged_patch, "cleared": merged_cleared},
        "user_action": derived_action,
    }
