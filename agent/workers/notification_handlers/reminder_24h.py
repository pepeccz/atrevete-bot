"""24h-before-appointment reminder handler."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.workers.notification_handlers._delivery import deliver_template
from agent.workers.notification_handlers._render_es import MADRID_TZ, fecha_es, hora_es
from agent.workers.notification_handlers._retry import next_retry_at
from agent.workers.notification_handlers.base import NotificationHandler
from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, Service
from shared.config import get_settings
from shared.settings_service import get_settings_service

logger = logging.getLogger(__name__)

WINDOW_LOWER = timedelta(hours=23)
WINDOW_UPPER = timedelta(hours=25)
BATCH_LIMIT = 50


async def query_fn(session: AsyncSession) -> list[Appointment]:
    """Return appointments that need a 24h reminder right now."""
    now = datetime.now(UTC)
    lower = now + WINDOW_LOWER
    upper = now + WINDOW_UPPER

    stmt = (
        select(Appointment)
        .options(selectinload(Appointment.customer))
        .where(
            Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]),
            Appointment.reminder_sent_at.is_(None),
            Appointment.reminder_failed.is_(False),
            Appointment.start_time >= lower,
            Appointment.start_time <= upper,
            or_(
                Appointment.reminder_next_retry_at.is_(None),
                Appointment.reminder_next_retry_at <= now,
            ),
        )
        .order_by(Appointment.start_time.asc())
        .limit(BATCH_LIMIT)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _build_body_params(appt: Appointment) -> dict[str, str]:
    """Build the 4 body params for the ``appointment_reminder_2h`` template.

    {{1}} name · {{2}} date (Madrid, Spanish) · {{3}} time · {{4}} service(s).
    """
    start = appt.start_time.astimezone(MADRID_TZ) if appt.start_time else None

    service_names: list[str] = []
    async with get_async_session() as session:
        if appt.service_ids:
            rows = await session.execute(
                select(Service.name).where(Service.id.in_(list(appt.service_ids)))
            )
            service_names = [name for (name,) in rows.all()]

    return {
        "1": appt.first_name or "",
        "2": fecha_es(start) if start else "",
        "3": hora_es(start) if start else "",
        "4": ", ".join(service_names),
    }


def _build_fallback_content(params: dict[str, str]) -> str:
    """Short castellano rendering of the template body, for Chatwoot fallback + DB storage."""
    return (
        f"Hola {params['1']}, te recordamos tu cita el {params['2']} a las {params['3']} "
        f"para {params['4']}. ¡Te esperamos!"
    )


async def send_fn(appt: Appointment, chatwoot_client: Any) -> bool:
    """Send the Meta template via Chatwoot. Return True on success."""
    settings = get_settings()
    svc = await get_settings_service()
    template = await svc.get(
        "whatsapp_template_reminder_24h",
        settings.WHATSAPP_TEMPLATE_REMINDER_24H,
    )
    if not template:
        logger.warning(
            "WHATSAPP_TEMPLATE_REMINDER_24H is empty — skipping appointment %s",
            appt.id,
        )
        return False

    phone = getattr(appt.customer, "phone", None) if appt.customer else None
    if not phone:
        logger.warning("Appointment %s has no customer phone — cannot send reminder", appt.id)
        return False

    body_params = await _build_body_params(appt)
    return await deliver_template(
        chatwoot_client,
        appt,
        template,
        body_params,
        _build_fallback_content(body_params),
    )


async def mark_sent_fn(session: AsyncSession, appointment_id: UUID) -> None:
    """Stamp reminder_sent_at atomically (no-op if already set)."""
    now = datetime.now(UTC)
    stmt = (
        update(Appointment)
        .where(
            and_(
                Appointment.id == appointment_id,
                Appointment.reminder_sent_at.is_(None),
            )
        )
        .values(reminder_sent_at=now, reminder_sent=True, reminder_failed=False)
    )
    await session.execute(stmt)


async def mark_failed_fn(session: AsyncSession, appointment_id: UUID) -> None:
    """Bump retry_count + schedule the next attempt via exponential backoff."""
    now = datetime.now(UTC)
    current = await session.get(Appointment, appointment_id)
    retry_count = (current.reminder_retry_count if current else 0) + 1
    stmt = (
        update(Appointment)
        .where(Appointment.id == appointment_id)
        .values(
            reminder_failed=True,
            reminder_retry_count=retry_count,
            reminder_next_retry_at=next_retry_at(retry_count, now=now),
        )
    )
    await session.execute(stmt)


HANDLER = NotificationHandler(
    name="reminder_24h",
    query_fn=query_fn,
    send_fn=send_fn,
    mark_sent_fn=mark_sent_fn,
    mark_failed_fn=mark_failed_fn,
)
