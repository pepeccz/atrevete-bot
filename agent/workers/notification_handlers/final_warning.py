"""Final-warning notification handler.

Fires the 'whatsapp_template_final_warning' Meta template for PENDING appointments
where the confirmation grace period has elapsed but auto-cancel has not fired yet.

State machine: confirm_sent (confirmation_sent_at) → grace → final_warning_sent
(final_warning_sent_at) → grace → CANCELLED (auto_cancel handler).

Only active when AUTO_CANCEL_ENABLED=true. Handler registration is gated in
notifications_worker._active_handlers() — this module is always importable.

Spec: S3-R2, S3-R5. Design: D-N2 (obs #7263).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.workers.notification_handlers._delivery import deliver_template
from agent.workers.notification_handlers._retry import next_retry_at
from agent.workers.notification_handlers.base import NotificationHandler
from database.models import Appointment, AppointmentStatus
from shared.config import get_settings
from shared.settings_service import get_settings_service

logger = logging.getLogger(__name__)

BATCH_LIMIT = 50


async def query_fn(session: AsyncSession) -> list[Appointment]:
    """Return PENDING appointments eligible for the final-warning template.

    Conditions (all must hold):
    - status = PENDING
    - confirmation_sent_at IS NOT NULL (has been asked to confirm)
    - final_warning_sent_at IS NULL (warning not yet sent — idempotency)
    - notification_failed = FALSE (backoff flag not set)
    - next_retry_at IS NULL OR next_retry_at <= now (backoff window elapsed)
    - now >= confirmation_sent_at + AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS (grace elapsed)
    - start_time > now + AUTO_CANCEL_MIN_LEAD_HOURS (appointment is not imminent)
    """
    settings = get_settings()
    now = datetime.now(UTC)
    grace_threshold = now - timedelta(hours=settings.AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS)
    min_lead_threshold = now + timedelta(hours=settings.AUTO_CANCEL_MIN_LEAD_HOURS)

    stmt = (
        select(Appointment)
        .options(selectinload(Appointment.customer))
        .where(
            and_(
                Appointment.status == AppointmentStatus.PENDING,
                Appointment.confirmation_sent_at.is_not(None),
                Appointment.final_warning_sent_at.is_(None),
                Appointment.notification_failed.is_(False),
                or_(
                    Appointment.next_retry_at.is_(None),
                    Appointment.next_retry_at <= now,
                ),
                Appointment.confirmation_sent_at <= grace_threshold,
                Appointment.start_time > min_lead_threshold,
            )
        )
        .order_by(Appointment.start_time.asc())
        .limit(BATCH_LIMIT)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _build_body_params(appt: Appointment) -> dict[str, str]:
    """Build WhatsApp template body params (same shape as confirm_48h)."""
    start = appt.start_time.astimezone(UTC) if appt.start_time else None
    return {
        "1": appt.first_name or "",
        "2": start.strftime("%Y-%m-%d") if start else "",
        "3": start.strftime("%H:%M") if start else "",
    }


def _build_fallback_content(params: dict[str, str]) -> str:
    """Short castellano rendering of the template body, for Chatwoot fallback + DB storage."""
    return (
        f"Hola {params['1']}, aún no hemos recibido tu confirmación para la cita del "
        f"{params['2']} a las {params['3']}. Si no confirmas pronto, se cancelará "
        "automáticamente."
    )


async def send_fn(appt: Appointment, chatwoot_client: Any) -> bool:
    """Send the final-warning WhatsApp template via Chatwoot.

    Reads the template name from system_settings at runtime (S3-R2).
    Returns False (graceful skip) when the template name is empty — Meta approval
    is a prerequisite and may not yet be granted (S3-G).
    """
    settings = get_settings()
    svc = await get_settings_service()
    template = await svc.get(
        "whatsapp_template_final_warning",
        settings.WHATSAPP_TEMPLATE_FINAL_WARNING,
    )
    if not template:
        logger.warning(
            "WHATSAPP_TEMPLATE_FINAL_WARNING is empty — skipping appointment %s (S3-G)",
            appt.id,
        )
        return False

    phone = getattr(appt.customer, "phone", None) if appt.customer else None
    if not phone:
        logger.warning("Appointment %s has no customer phone — cannot send final warning", appt.id)
        return False

    body_params = _build_body_params(appt)
    return await deliver_template(
        chatwoot_client,
        appt,
        template,
        body_params,
        _build_fallback_content(body_params),
    )


async def mark_sent_fn(session: AsyncSession, appointment_id: UUID) -> None:
    """Stamp final_warning_sent_at with a CAS guard (idempotent, mirrors confirm_48h)."""
    now = datetime.now(UTC)
    stmt = (
        update(Appointment)
        .where(
            and_(
                Appointment.id == appointment_id,
                Appointment.final_warning_sent_at.is_(None),
            )
        )
        .values(final_warning_sent_at=now, notification_failed=False)
    )
    await session.execute(stmt)


async def mark_failed_fn(session: AsyncSession, appointment_id: UUID) -> None:
    """Bump retry counter and schedule next attempt (reuses confirm_48h retry columns).

    Safe to reuse: confirm phase (confirmation_sent_at IS NULL) and warning phase
    (confirmation_sent_at IS NOT NULL AND final_warning_sent_at IS NULL) are mutually
    exclusive per row — they never contend simultaneously (design D-N2, obs #7263).
    """
    now = datetime.now(UTC)
    current = await session.get(Appointment, appointment_id)
    retry_count = (current.retry_count if current else 0) + 1
    stmt = (
        update(Appointment)
        .where(Appointment.id == appointment_id)
        .values(
            notification_failed=True,
            retry_count=retry_count,
            next_retry_at=next_retry_at(retry_count, now=now),
        )
    )
    await session.execute(stmt)


HANDLER = NotificationHandler(
    name="final_warning",
    query_fn=query_fn,
    send_fn=send_fn,
    mark_sent_fn=mark_sent_fn,
    mark_failed_fn=mark_failed_fn,
)
