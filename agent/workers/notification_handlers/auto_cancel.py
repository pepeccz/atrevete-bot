"""Auto-cancel notification handler.

Atomically cancels PENDING appointments where the final-warning grace period has
elapsed and the appointment is still far enough in the future that freeing the
slot is meaningful (MIN_LEAD_HOURS guard).

No WhatsApp template send — the action IS the DB state change + GCal delete.
Idempotency is guaranteed by the `status = PENDING` filter in query_fn alone:
once cancelled, the row never re-enters the batch.

Only active when AUTO_CANCEL_ENABLED=true. Handler registration is gated in
notifications_worker._active_handlers() — this module is always importable.

Spec: S3-R4, S3-R6, S3-R7, S3-R8, S3-R9. Design: D-N2, D-R7 (obs #7263).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.services.gcal_push_service import delete_gcal_event
from agent.workers.notification_handlers.base import NotificationHandler
from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, Notification, NotificationType
from shared.config import get_settings

logger = logging.getLogger(__name__)

BATCH_LIMIT = 50


async def query_fn(session: AsyncSession) -> list[Appointment]:
    """Return PENDING appointments eligible for auto-cancellation.

    Conditions (all must hold):
    - status = PENDING (S3-R9 hard invariant; CONFIRMED never swept)
    - final_warning_sent_at IS NOT NULL (warning was sent)
    - now >= final_warning_sent_at + AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS (grace elapsed)
    - start_time > now + AUTO_CANCEL_MIN_LEAD_HOURS (appointment still far enough; S3-J)

    Deliberately excludes notification_failed/next_retry_at backoff columns because
    this handler performs a DB action (no Chatwoot call), and the idempotency is
    guaranteed by the status=PENDING filter (not by retry state).
    """
    settings = get_settings()
    now = datetime.now(UTC)
    grace_threshold = now - timedelta(hours=settings.AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS)
    min_lead_threshold = now + timedelta(hours=settings.AUTO_CANCEL_MIN_LEAD_HOURS)

    stmt = (
        select(Appointment)
        .where(
            and_(
                Appointment.status == AppointmentStatus.PENDING,
                Appointment.final_warning_sent_at.is_not(None),
                Appointment.final_warning_sent_at <= grace_threshold,
                Appointment.start_time > min_lead_threshold,
            )
        )
        .order_by(Appointment.start_time.asc())
        .limit(BATCH_LIMIT)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def send_fn(appt: Appointment, _chatwoot_client: Any) -> bool:
    """Atomically cancel the appointment and clean up GCal/Notifications.

    Opens its own session (mirrors paused_24h.py pattern) to perform a CAS
    re-fetch before mutating state — prevents double-cancel races (S3-R8).

    Returns True regardless of GCal outcome — the DB transition is the source
    of truth; GCal failure is logged but does not roll back the cancellation.
    """
    try:
        async with get_async_session() as session:
            # CAS re-fetch: if already CANCELLED (concurrent worker tick), short-circuit
            result = await session.execute(
                select(Appointment).where(Appointment.id == appt.id)
            )
            fetched = result.scalars().first()

            if fetched is None:
                logger.warning("auto_cancel: appointment %s not found on re-fetch", appt.id)
                return True

            if fetched.status != AppointmentStatus.PENDING:
                # Already transitioned by another path (operator, customer, concurrent tick)
                logger.info(
                    "auto_cancel: appointment %s is not PENDING on re-fetch (status=%s) — no-op",
                    appt.id,
                    fetched.status,
                )
                return True

            # Single atomic commit: status change + Notification in the same transaction
            # so a mid-flight failure cannot leave the appointment CANCELLED without a
            # corresponding Notification row (WARNING-3 fix).
            now = datetime.now(UTC)
            fetched.status = AppointmentStatus.CANCELLED
            fetched.cancelled_at = now
            fetched.cancellation_reason = "auto_cancelled_no_confirmation"  # S3-R4 canonical string

            notification = Notification(
                id=uuid4(),
                type=NotificationType.AUTO_CANCELLED,
                title="Cita cancelada automáticamente",
                message=(
                    f"La cita {appt.id} fue cancelada por falta de confirmación "
                    "(auto_cancelled_no_confirmation)."
                ),
                entity_type="appointment",
                entity_id=appt.id,
                is_read=False,
                is_starred=False,
            )
            session.add(notification)
            await session.commit()

            logger.info(
                "auto_cancel: appointment %s cancelled (cancellation_reason=auto_cancelled_no_confirmation)",
                appt.id,
            )

    except Exception:
        logger.exception("auto_cancel: unexpected error processing appointment %s", appt.id)
        return False

    # Fire-and-forget GCal delete (outside the session context to avoid holding the
    # session open; GCal failure MUST NOT roll back the DB cancel — S3-R7).
    if appt.google_calendar_event_id:
        try:
            await delete_gcal_event(
                stylist_id=appt.stylist_id,
                event_id=appt.google_calendar_event_id,
                appointment_id=appt.id,
            )
        except Exception:
            logger.exception(
                "auto_cancel: GCal delete failed for appointment %s "
                "(DB already CANCELLED — not rolling back)",
                appt.id,
            )

    return True


async def mark_sent_fn(session: AsyncSession, appointment_id: UUID) -> None:
    """No-op: state captured by status=CANCELLED leaving the query on the next tick."""
    _ = appointment_id


async def mark_failed_fn(session: AsyncSession, appointment_id: UUID) -> None:
    """No-op: idempotency via status=PENDING filter; no retry backoff needed for DB actions."""
    _ = appointment_id


HANDLER = NotificationHandler(
    name="auto_cancel",
    query_fn=query_fn,
    send_fn=send_fn,
    mark_sent_fn=mark_sent_fn,
    mark_failed_fn=mark_failed_fn,
)
