"""Resolver registry — pre-loop deterministic resolvers per P3 + structured telemetry per P10.

The registry is a module-level singleton dict. Insertion order is preserved (Python 3.7+).
Capabilities register their resolvers at module-import time (in E2). E1 has zero live
registrations; tests register/unregister via fixtures and call _clear_for_tests() in teardown.

Telemetry contract (P10 + spec R6):
  - Sink: stdlib logging at INFO via logger.info("resolver.invoke", extra={...}).
  - 7 required fields: resolver, conversation_id, turn, user_text_hash (SHA-256[:16]),
    matched, fuzzy_distance (-1.0 when N/A), matched_phrase.
  - Raw user_text is NEVER logged (privacy + spec R6 MUST NOT).
  - The project JSONFormatter (shared/logging_config.py) propagates extra= keys into JSON.
  - Tests access log fields via caplog.records[i].fieldname (extra= merges into LogRecord.__dict__).
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.state.schemas import ConversationState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

StatePatch = dict[str, Any]
Resolver = Callable[[str, "ConversationState"], StatePatch | None]

# ---------------------------------------------------------------------------
# Module-level singleton registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Resolver] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register(name: str, resolver: Resolver) -> None:
    """Register a resolver under *name*. Raises ValueError if name is already taken."""
    if name in _REGISTRY:
        raise ValueError(f"Resolver {name!r} already registered; unregister first")
    _REGISTRY[name] = resolver


def unregister(name: str) -> None:
    """Remove resolver by name. Raises KeyError if name is not registered."""
    del _REGISTRY[name]


def get(name: str) -> Resolver:
    """Return the resolver registered under *name*. Raises KeyError if absent."""
    return _REGISTRY[name]


def get_ordered(names: list[str]) -> list[Resolver]:
    """Return resolvers in the caller-supplied order. Raises KeyError on any missing name."""
    return [_REGISTRY[n] for n in names]


def registered_names() -> list[str]:
    """Return resolver names in insertion order."""
    return list(_REGISTRY.keys())


def _clear_for_tests() -> None:
    """Test-only escape hatch — never used in production code."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Telemetry execution helper
# ---------------------------------------------------------------------------


def invoke_with_telemetry(
    name: str,
    user_text: str,
    state: ConversationState,
    *,
    conversation_id: str | None = None,
    turn: int = 0,
) -> StatePatch | None:
    """Execute a registered resolver and emit a structured P10 telemetry log record.

    Resolvers MAY embed match details in the patch under the private '_telemetry' key:
      {"_telemetry": {"matched_phrase": str, "fuzzy_distance": float}}
    Those values surface in the log record for downstream analysis.
    """
    resolver = _REGISTRY[name]
    text_hash = hashlib.sha256(user_text.encode("utf-8")).hexdigest()[:16]

    patch = resolver(user_text, state)
    matched = patch is not None
    matched_phrase = ""
    fuzzy_distance = -1.0

    if isinstance(patch, dict):
        meta = patch.get("_telemetry")
        if isinstance(meta, dict):
            matched_phrase = str(meta.get("matched_phrase", ""))
            try:
                fuzzy_distance = float(meta.get("fuzzy_distance", -1.0))
            except (TypeError, ValueError):
                fuzzy_distance = -1.0

    logger.info(
        "resolver.invoke",
        extra={
            "resolver": name,
            "conversation_id": conversation_id,
            "turn": turn,
            "user_text_hash": text_hash,
            "matched": matched,
            "matched_phrase": matched_phrase,
            "fuzzy_distance": fuzzy_distance,
        },
    )
    return patch
