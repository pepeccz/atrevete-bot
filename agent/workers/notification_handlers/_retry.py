"""Retry helpers shared by notification handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def exponential_backoff(retry_count: int) -> timedelta:
    """Return the next retry delay: ``10min * 2^retry_count`` capped at 24h."""
    base_minutes = 10 * (2**retry_count)
    max_minutes = 24 * 60
    return timedelta(minutes=min(base_minutes, max_minutes))


def next_retry_at(retry_count: int, *, now: datetime | None = None) -> datetime:
    """Return the absolute timestamp for the next retry attempt."""
    current = now if now is not None else datetime.now(UTC)
    return current + exponential_backoff(retry_count)
