"""48h-before-appointment confirmation-request handler."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.workers.notification_handlers._retry import next_retry_at
from agent.workers.notification_handlers.base import NotificationHandler
from database.models import Appointment, AppointmentStatus
from shared.config import get_settings
from shared.settings_service import get_settings_service

logger = logging.getLogger(__name__)

WINDOW_LOWER = timedelta(hours=47)
WINDOW_UPPER = timedelta(hours=49)
BATCH_LIMIT = 50


async def query_fn(session: AsyncSession) -> list[Appointment]:
    """Return PENDING appointments that need a 48h confirmation request."""
    now = datetime.now(UTC)
    lower = now + WINDOW_LOWER
    upper = now + WINDOW_UPPER

    stmt = (
        select(Appointment)
        .options(selectinload(Appointment.customer))
        .where(
            Appointment.status == AppointmentStatus.PENDING,
            Appointment.confirmation_sent_at.is_(None),
            Appointment.notification_failed.is_(False),
            Appointment.start_time >= lower,
            Appointment.start_time <= upper,
            or_(
                Appointment.next_retry_at.is_(None),
                Appointment.next_retry_at <= now,
            ),
        )
        .order_by(Appointment.start_time.asc())
        .limit(BATCH_LIMIT)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _build_body_params(appt: Appointment) -> dict[str, str]:
    start = appt.start_time.astimezone(UTC) if appt.start_time else None
    return {
        "1": appt.first_name or "",
        "2": start.strftime("%Y-%m-%d") if start else "",
        "3": start.strftime("%H:%M") if start else "",
    }


async def send_fn(appt: Appointment, chatwoot_client: Any) -> bool:
    settings = get_settings()
    svc = await get_settings_service()
    template = await svc.get(
        "whatsapp_template_confirm_48h",
        settings.WHATSAPP_TEMPLATE_CONFIRM_48H,
    )
    if not template:
        logger.warning(
            "WHATSAPP_TEMPLATE_CONFIRM_48H is empty — skipping appointment %s",
            appt.id,
        )
        return False

    phone = getattr(appt.customer, "phone", None) if appt.customer else None
    if not phone:
        logger.warning(
            "Appointment %s has no customer phone — cannot send confirmation request", appt.id
        )
        return False

    return await chatwoot_client.send_template_message(
        customer_phone=phone,
        template_name=template,
        body_params=_build_body_params(appt),
        category="UTILITY",
        language="es",
    )


async def mark_sent_fn(session: AsyncSession, appointment_id: UUID) -> None:
    now = datetime.now(UTC)
    stmt = (
        update(Appointment)
        .where(
            and_(
                Appointment.id == appointment_id,
                Appointment.confirmation_sent_at.is_(None),
            )
        )
        .values(confirmation_sent_at=now, notification_failed=False)
    )
    await session.execute(stmt)


async def mark_failed_fn(session: AsyncSession, appointment_id: UUID) -> None:
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
    name="confirm_48h",
    query_fn=query_fn,
    send_fn=send_fn,
    mark_sent_fn=mark_sent_fn,
    mark_failed_fn=mark_failed_fn,
)
