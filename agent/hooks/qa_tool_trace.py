"""QA-only Redis stream tracing for agent tool calls."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from shared.redis_client import get_redis_client


logger = logging.getLogger(__name__)
QA_TOOL_TRACE_STREAM_PREFIX = "qa_tool_trace"


def qa_tool_trace_stream(conversation_id: str) -> str:
    """Return the Redis stream name used for QA tool tracing."""
    return f"{QA_TOOL_TRACE_STREAM_PREFIX}:{conversation_id}"


def _serialize_trace_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _serialize_trace_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_trace_value(item) for item in value]
    return value


async def record_tool_calls(
    conversation_id: str,
    turn_index: int,
    tool_events: Sequence[Mapping[str, Any]],
) -> None:
    """Persist QA tool calls to a Redis stream without affecting user behavior."""
    if not conversation_id or not tool_events:
        return

    redis_client = get_redis_client()
    stream_name = qa_tool_trace_stream(conversation_id)

    for event in tool_events:
        tool_name = str(event.get("tool_name") or "").strip()
        if not tool_name:
            continue

        payload = {
            "turn_index": str(turn_index),
            "tool_name": tool_name,
            "args": json.dumps(_serialize_trace_value(event.get("arguments") or {}), default=str),
            "result": json.dumps(_serialize_trace_value(event.get("result")), default=str),
            "source": str(event.get("source") or "hook"),
            "timestamp": str(
                _serialize_trace_value(event.get("timestamp"))
                or datetime.now(UTC).isoformat()
            ),
        }
        await redis_client.xadd(stream_name, payload)


def schedule_tool_call_recording(
    conversation_id: str,
    turn_index: int,
    tool_events: Sequence[Mapping[str, Any]],
) -> bool:
    """Schedule background QA tool-call persistence on the active event loop."""
    if not conversation_id or not tool_events:
        return False

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("Skipping QA tool trace scheduling without running loop")
        return False

    loop.create_task(record_tool_calls(conversation_id, turn_index, tool_events))
    return True
