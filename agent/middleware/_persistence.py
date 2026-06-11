"""Persistence helper — encapsulates the middleware→checkpoint boundary.

Single canonical function for persisting scalar AgentState fields to the
LangGraph checkpoint via ExtendedModelResponse + Command(update=...).

Generalises the two prod-proven patterns:
- CustomerResolveMiddleware O2 fix (customer_id / customer_name)
- AvailabilityContextMiddleware Change-P fix (recently_offered_slots)

into one reusable helper with a well-tested coercion table.

ADR-1 coercion table:
    UUID (incl. asyncpg pgproto) → str(v)
    datetime / date              → v.isoformat()
    None / str / int / float / bool → passthrough
    dict                         → shallow-coerce values (one level)
    list                         → coerce items (shallow)
    anything else                → raise TypeError(field, type)

Guards (hard — raises ValueError):
    key "messages"      → would corrupt add_messages reducer history
    key "_slot_*"       → overlay-only by definition; persisting wastes checkpoint storage

Spec: REQ-S1-1 through REQ-S1-5
Design: ADR-1
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import ExtendedModelResponse, ModelResponse
from langgraph.types import Command

# ---------------------------------------------------------------------------
# Internal coercion helpers
# ---------------------------------------------------------------------------

_FORBIDDEN_KEYS = frozenset({"messages"})
_FORBIDDEN_PREFIX = "_slot_"


def _coerce_value(field: str, value: Any) -> Any:
    """Coerce a single value to a checkpoint-safe type.

    Raises TypeError if the type is not in the coercion table.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    # UUID — both stdlib and asyncpg pgproto UUID
    if isinstance(value, uuid.UUID):
        return str(value)
    try:
        # asyncpg.pgproto.pgproto.UUID does not subclass uuid.UUID
        # but its str() representation is the canonical UUID string.
        import asyncpg.pgproto.pgproto as _pgproto  # type: ignore[import]

        if isinstance(value, _pgproto.UUID):
            return str(value)
    except ImportError:
        pass

    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {k: _coerce_value(f"{field}.{k}", v) for k, v in value.items()}

    if isinstance(value, list):
        return [_coerce_value(f"{field}[{i}]", item) for i, item in enumerate(value)]

    raise TypeError(
        f"persist_to_checkpoint: field {field!r} has unsupported type "
        f"{type(value).__name__!r} — add coercion to _persistence.py or "
        "pre-coerce the value before calling persist_to_checkpoint()"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def coerce_state_delta(delta: Mapping[str, Any]) -> dict[str, Any]:
    """Validate keys and coerce all values in delta to checkpoint-safe types.

    Raises ValueError for forbidden keys (messages, _slot_*).
    Raises TypeError for unsupported value types.
    """
    coerced: dict[str, Any] = {}
    for key, value in delta.items():
        if key in _FORBIDDEN_KEYS:
            raise ValueError(
                f"persist_to_checkpoint: key {key!r} is forbidden — "
                f"'messages' is managed exclusively by the add_messages reducer. "
                "Persisting the compacted list would corrupt history. "
                "Only scalar fields (last_summarized_msg_count, conversation_summary, …) "
                "may be persisted via this helper."
            )
        if key.startswith(_FORBIDDEN_PREFIX):
            raise ValueError(
                f"persist_to_checkpoint: key {key!r} starts with '_slot_' — "
                "slot keys are per-turn overlay material regenerated each turn. "
                "They must NOT be persisted to the checkpoint. "
                "Use request.override(state={{…}}) for slot-writer middlewares."
            )
        coerced[key] = _coerce_value(key, value)
    return coerced


def persist_to_checkpoint(response: ModelResponse, delta: Mapping[str, Any]) -> ModelResponse:
    """Wrap response in ExtendedModelResponse to persist scalar fields to LangGraph checkpoint.

    Usage in awrap_model_call:
        response = await handler(modified_request)
        return persist_to_checkpoint(response, {"customer_id": cid, ...})

    Empty delta contract (REQ-S1-5): when delta is {}, returns the original
    response unwrapped (NOT an ExtendedModelResponse). This avoids unnecessary
    checkpoint writes.

    Coercion is applied per ADR-1 before constructing the Command.

    Raises ValueError for forbidden keys (messages, _slot_*).
    Raises TypeError for unsupported value types.

    Spec: REQ-S1-1 through REQ-S1-5
    Design: ADR-1
    """
    coerced = coerce_state_delta(delta)
    if not coerced:
        return response
    return ExtendedModelResponse(model_response=response, command=Command(update=coerced))
