"""Notifications worker — scheduled WhatsApp template delivery.

Polls eligible appointments for two template categories and, for each:
- fetches the batch via the handler's ``query_fn``
- calls Chatwoot via the handler's ``send_fn``
- on success: ``mark_sent_fn`` (atomic, idempotent)
- on failure: ``mark_failed_fn`` (bumps retry counter + schedules next attempt)

Feature-flagged via ``NOTIFICATIONS_WORKER_ENABLED``. Default False until the
Meta-approved templates are populated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.workers.notification_handlers import NotificationHandler
from agent.workers.notification_handlers.auto_cancel import HANDLER as auto_cancel_handler
from agent.workers.notification_handlers.confirm_48h import HANDLER as confirm_48h_handler
from agent.workers.notification_handlers.final_warning import HANDLER as final_warning_handler
from agent.workers.notification_handlers.paused_24h import HANDLER as paused_24h_handler
from agent.workers.notification_handlers.reminder_24h import HANDLER as reminder_24h_handler
from database.connection import get_async_session
from shared.chatwoot_client import ChatwootClient
from shared.config import get_settings

logger = logging.getLogger(__name__)

HEARTBEAT_PATH = Path("/tmp/notifications_worker_heartbeat.json")


def _active_handlers(settings: Any) -> dict[str, NotificationHandler]:
    """Build the active handler dict based on current settings.

    Base handlers (reminder_24h, confirm_48h, paused_24h) are always active when
    NOTIFICATIONS_WORKER_ENABLED=true. The destructive tail (final_warning +
    auto_cancel) is added ONLY when AUTO_CANCEL_ENABLED=true.

    Re-evaluated every worker tick so AUTO_CANCEL_ENABLED can be toggled without
    a restart (S3-R11 kill-switch immediacy).
    """
    base: dict[str, NotificationHandler] = {
        reminder_24h_handler.name: reminder_24h_handler,
        confirm_48h_handler.name: confirm_48h_handler,
        # SC-8: daily in-app reminder for conversations paused > 24h (conversaciones-inbox)
        paused_24h_handler.name: paused_24h_handler,
    }
    if getattr(settings, "AUTO_CANCEL_ENABLED", False):
        base[final_warning_handler.name] = final_warning_handler
        base[auto_cancel_handler.name] = auto_cancel_handler
    return base


# Module-level alias for backward compatibility with tests/imports that reference
# HANDLERS directly (e.g. test_notifications_worker.py).
# Contains the 3 always-active base handlers only — main_loop uses _active_handlers()
# each tick to include the flag-gated handlers when AUTO_CANCEL_ENABLED=true.
HANDLERS: dict[str, NotificationHandler] = {
    reminder_24h_handler.name: reminder_24h_handler,
    confirm_48h_handler.name: confirm_48h_handler,
    # SC-8: daily in-app reminder for conversations paused > 24h (conversaciones-inbox)
    paused_24h_handler.name: paused_24h_handler,
}

_shutdown_requested = False


def _install_signal_handlers() -> None:
    def _handler(signum: int, _frame: Any) -> None:
        global _shutdown_requested
        logger.info("Received signal %s — shutting down notifications worker", signum)
        _shutdown_requested = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Not in main thread (tests) — skip.
            pass


async def _write_heartbeat() -> None:
    """Write a heartbeat file consumed by the Docker healthcheck."""
    payload = {"timestamp": time.time(), "iso": datetime.now(UTC).isoformat()}
    try:
        HEARTBEAT_PATH.write_text(json.dumps(payload))
    except OSError as exc:
        logger.warning("Failed to write notifications worker heartbeat: %s", exc)


def is_heartbeat_stale(path: Path, max_age_seconds: float, now: float | None = None) -> bool:
    """Return True when the heartbeat file is missing or older than `max_age_seconds`.

    Mirrors the logic used by the Docker healthcheck CMD so it is unit-testable.
    """
    if not path.exists():
        return True
    current = now if now is not None else time.time()
    return (current - path.stat().st_mtime) > max_age_seconds


async def process_handler(
    handler: NotificationHandler,
    chatwoot_client: ChatwootClient,
) -> int:
    """Run one pass of a single handler. Returns the number of successful sends."""
    sent = 0
    async with get_async_session() as session:
        try:
            batch = await handler.query_fn(session)
        except Exception:
            logger.exception("Handler %s query_fn failed", handler.name)
            return 0

    for appt in batch:
        success = False
        try:
            success = await handler.send_fn(appt, chatwoot_client)
        except Exception:
            logger.exception("Handler %s send_fn raised for appt %s", handler.name, appt.id)
            success = False

        # Commit mark_sent BEFORE any further work — at-least-once over
        # at-most-once: if commit fails, the row stays eligible and we retry.
        async with get_async_session() as session:
            try:
                if success:
                    await handler.mark_sent_fn(session, appt.id)
                    await session.commit()
                    sent += 1
                else:
                    await handler.mark_failed_fn(session, appt.id)
                    await session.commit()
            except Exception:
                logger.exception(
                    "Handler %s mark_*_fn commit failed for appt %s", handler.name, appt.id
                )
                await session.rollback()
    return sent


async def main_loop() -> None:
    """Poll-sleep-poll until a shutdown signal is received."""
    settings = get_settings()
    chatwoot_client = ChatwootClient()
    interval = settings.NOTIFICATIONS_POLL_INTERVAL_SECONDS

    logger.info(
        "Notifications worker loop started (interval=%ss, AUTO_CANCEL_ENABLED=%s)",
        interval,
        getattr(settings, "AUTO_CANCEL_ENABLED", False),
    )

    while not _shutdown_requested:
        # Re-evaluate each tick so AUTO_CANCEL_ENABLED can be toggled without restart (S3-R11).
        active = _active_handlers(settings)
        logger.debug(
            "notifications_worker tick: active handlers=%s AUTO_CANCEL_ENABLED=%s",
            list(active),
            getattr(settings, "AUTO_CANCEL_ENABLED", False),
        )
        for handler in active.values():
            try:
                await process_handler(handler, chatwoot_client)
            except Exception:
                logger.exception("Unhandled error in handler %s", handler.name)
        await _write_heartbeat()

        # Sleep in small slices so SIGTERM is honoured promptly.
        slept = 0
        while slept < interval and not _shutdown_requested:
            await asyncio.sleep(min(5, interval - slept))
            slept += 5


async def main() -> int:
    """Entry point. Respects the ``NOTIFICATIONS_WORKER_ENABLED`` flag."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    settings = get_settings()
    if not settings.NOTIFICATIONS_WORKER_ENABLED:
        logger.info("NOTIFICATIONS_WORKER_ENABLED=False — exiting without polling")
        return 0

    _install_signal_handlers()
    await _write_heartbeat()
    try:
        await main_loop()
    except Exception:
        logger.exception("Notifications worker crashed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
