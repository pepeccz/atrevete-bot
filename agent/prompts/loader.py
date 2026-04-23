"""Prompt loader — assembles the static system prompt once at startup.

load_system_prompt() -> str
    Concatenates identity.md + critical_rules.md + glossary.md.
    Result is cached at module level via functools.lru_cache (single load per process).

_TtlCache
    Shared TTL-cache utility used by catalog_builder and other async loaders.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

_SHARED_DIR = Path(__file__).parent / "shared"

T = TypeVar("T")


class _TtlCache(Generic[T]):
    """Simple async TTL cache for a single value.

    Usage::

        cache = _TtlCache(ttl_minutes=5)
        value = await cache.get_or_load(async_loader_fn)
        cache.invalidate()  # force refresh on next call
    """

    def __init__(self, ttl_minutes: int = 5) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._value: T | None = None
        self._loaded_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def get_or_load(self, loader: Callable[[], Awaitable[T]]) -> T:
        """Return cached value or call loader to refresh."""
        now = datetime.utcnow()
        if self._value is not None and self._loaded_at is not None:
            if now - self._loaded_at < self._ttl:
                return self._value

        async with self._lock:
            # Double-check after acquiring lock
            now = datetime.utcnow()
            if self._value is not None and self._loaded_at is not None:
                if now - self._loaded_at < self._ttl:
                    return self._value

            self._value = await loader()
            self._loaded_at = now
            return self._value  # type: ignore[return-value]

    def invalidate(self) -> None:
        """Force the next call to re-run the loader."""
        self._loaded_at = None


def _read(filename: str) -> str:
    """Read a file from agent/prompts/shared/. Returns empty string on error."""
    path = _SHARED_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


@functools.lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """Assemble and cache the static system prompt.

    Concatenates (in order):
        1. shared/identity.md    — Maite persona
        2. shared/critical_rules.md — EU-AI-Act disclosure, UUID rule, Spanish-only
        3. shared/glossary.md    — audience taxonomy + service tag glossary

    Returns:
        str: Full system prompt, newline-separated sections.
    """
    sections = [
        _read("identity.md"),
        _read("critical_rules.md"),
        _read("glossary.md"),
        _read("booking_flow.md"),
        _read("appointment_management_flow.md"),
    ]
    return "\n\n---\n\n".join(s for s in sections if s)
