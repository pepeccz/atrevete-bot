"""Tracing context: ContextVar carrying per-turn trace metadata.

The ContextVar is set by LLMTraceMiddleware at turn entry and reset at turn exit.
httpx hooks read it to correlate HTTP calls with conversation turns.

Design: ADR-2 (ContextVar over header injection) — task-local, propagates
through await chains, no semantic pollution of outbound payloads.
"""

from __future__ import annotations

import itertools
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TraceContext:
    """Per-turn trace metadata.

    One instance is created per middleware invocation (per agent turn).
    seq starts at 0 and increments monotonically within the turn — shared
    across main LLM calls, summarizer calls, and retries within the same turn.
    """

    conversation_id: str
    turn_started_at: datetime
    seq: itertools.count = field(default_factory=lambda: itertools.count(0))


#: Task-local ContextVar carrying the current turn's trace metadata.
#: Default is None (sentinel for "no active trace scope").
current_trace_ctx: ContextVar[TraceContext | None] = ContextVar(
    "agent.tracing.context.current_trace_ctx",
    default=None,
)


def safe_conversation_id(cid: str) -> str:
    """Return a filesystem-safe version of conversation_id.

    Replaces ':' with '__' so thread IDs like 'v2:uuid' become 'v2__uuid'.
    This is reversible and unambiguous — no information is lost.

    Design: ADR-7 (colon replacement ':' → '__').
    """
    return cid.replace(":", "__")


def format_ts(dt: datetime) -> str:
    """Return a colon-free ISO-like timestamp string for use in filenames.

    Example: datetime(2026, 5, 16, 14, 32, 1, 123000) → '2026-05-16T14-32-01-123Z'

    Colons are replaced with hyphens for filesystem portability.
    Millisecond precision is included (not microseconds) for human readability.
    """
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H-%M-%S-") + f"{ms:03d}Z"
