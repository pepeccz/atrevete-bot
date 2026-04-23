"""Handler contract for the notifications worker.

Each scheduled notification (24h reminder, 48h confirmation) is expressed as a
``NotificationHandler`` dataclass. The worker iterates the registry and for each
handler: queries eligible appointments → sends a template → records success or
bumps the retry counter. Per-appointment state is owned by the handler.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationHandler:
    """Registry entry wiring query / send / mark-sent / mark-failed callables."""

    name: str
    query_fn: Callable[..., Awaitable[list]]
    send_fn: Callable[..., Awaitable[bool]]
    mark_sent_fn: Callable[..., Awaitable[None]]
    mark_failed_fn: Callable[..., Awaitable[None]]
