"""Notification service helpers for agent-side notification creation.

Provides reusable helpers for creating and resolving admin panel Notification
rows from within agent services. Currently supports:
  - create_gcal_push_failed_notification: creates a deduplicated GCAL_PUSH_FAILED row
  - resolve_gcal_push_failed_notification: marks the open notification as read on sync success

Design: D3 (gcal-sync-resilience). Mirrors the paused_24h notification pattern.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Notification, NotificationType

logger = logging.getLogger(__name__)


async def create_gcal_push_failed_notification(
    session: AsyncSession,
    appointment_id: UUID,
) -> Notification | None:
    """Create a GCAL_PUSH_FAILED notification for an appointment, with deduplication.

    If an unread notification of this type already exists for the appointment,
    no new row is created and None is returned (prevents duplicate bell entries
    when the operator retries and fails again).

    The caller is responsible for committing the session.

    Args:
        session: Active async SQLAlchemy session.
        appointment_id: UUID of the affected appointment.

    Returns:
        The new Notification instance if created, None if deduped.
    """
    existing_result = await session.execute(
        select(Notification).where(
            Notification.entity_type == "appointment",
            Notification.entity_id == appointment_id,
            Notification.type == NotificationType.GCAL_PUSH_FAILED,
            Notification.is_read.is_(False),
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        logger.debug(
            "gcal_push_failed: notification already exists for appointment %s — skipping",
            appointment_id,
        )
        return None

    notif = Notification(
        id=uuid4(),
        type=NotificationType.GCAL_PUSH_FAILED,
        title="Error sincronización Google Calendar",
        message="La sincronización de la cita con Google Calendar falló tras 3 intentos.",
        entity_type="appointment",
        entity_id=appointment_id,
        is_read=False,
        is_starred=False,
    )
    session.add(notif)
    logger.info(
        "gcal_push_failed: created notification for appointment %s", appointment_id
    )
    return notif


async def resolve_gcal_push_failed_notification(
    session: AsyncSession,
    appointment_id: UUID,
) -> None:
    """Mark the open GCAL_PUSH_FAILED notification as read on successful retry.

    This is called when a previously-failed appointment is successfully synced
    (gcal_sync_status transitions from 'failed' to 'synced').

    The caller is responsible for committing the session.

    Args:
        session: Active async SQLAlchemy session.
        appointment_id: UUID of the appointment that just synced successfully.
    """
    existing_result = await session.execute(
        select(Notification).where(
            Notification.entity_type == "appointment",
            Notification.entity_id == appointment_id,
            Notification.type == NotificationType.GCAL_PUSH_FAILED,
            Notification.is_read.is_(False),
        )
    )
    notif = existing_result.scalar_one_or_none()
    if notif is None:
        return

    notif.is_read = True
    notif.read_at = datetime.now(UTC)
    logger.info(
        "gcal_push_failed: resolved notification for appointment %s", appointment_id
    )
