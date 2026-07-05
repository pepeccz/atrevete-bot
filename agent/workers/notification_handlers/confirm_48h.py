"""48h-before-appointment confirmation-request handler."""

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
from database.models import Appointment, AppointmentStatus, Service, Stylist
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


async def _build_body_params(appt: Appointment, settings: Any) -> dict[str, str]:
    """Build the 6 body params for the ``appointment_confirmation_48h`` template.

    {{1}} name · {{2}} date · {{3}} time · {{4}} stylist · {{5}} service(s) ·
    {{6}} auto-cancel deadline. Stylist/service names are resolved from the DB;
    dates are rendered in Europe/Madrid so the customer sees the real local time.

    The {{6}} deadline is the earliest instant the auto-cancel tail could
    actually fire, anchored on "now" (≈ ``confirmation_sent_at``, stamped right
    after this send) — NOT a fixed T-24h offset from ``start_time``. Mirrors the
    same two-grace-period composition the ``final_warning``/``auto_cancel``
    handlers use: earliest final_warning = confirmation_sent_at +
    ``AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS``; earliest auto_cancel =
    final_warning_sent_at + ``AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS``. A fixed
    T-24h promise could be hours later than the real earliest cancel instant
    with non-default settings (sdd/context-coherence FIX 3).
    """
    start = appt.start_time.astimezone(MADRID_TZ) if appt.start_time else None

    stylist_name = ""
    service_names: list[str] = []
    async with get_async_session() as session:
        if appt.stylist_id:
            stylist = await session.get(Stylist, appt.stylist_id)
            stylist_name = getattr(stylist, "name", "") or ""
        if appt.service_ids:
            rows = await session.execute(
                select(Service.name).where(Service.id.in_(list(appt.service_ids)))
            )
            service_names = [name for (name,) in rows.all()]

    now = datetime.now(UTC)
    deadline_utc = now + timedelta(
        hours=settings.AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS
        + settings.AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS
    )
    deadline = deadline_utc.astimezone(MADRID_TZ)
    deadline_str = f"{fecha_es(deadline)} a las {hora_es(deadline)}"

    return {
        "1": appt.first_name or "",
        "2": fecha_es(start) if start else "",
        "3": hora_es(start) if start else "",
        "4": stylist_name,
        "5": ", ".join(service_names),
        "6": deadline_str,
    }


def _build_fallback_content(params: dict[str, str]) -> str:
    """Short castellano rendering of the template body, for Chatwoot fallback + DB storage."""
    return (
        f"Hola {params['1']}, ¿confirmas tu cita del {params['2']} a las {params['3']} "
        f"con {params['4']} para {params['5']}? Si no confirmas antes del {params['6']}, "
        "la cita se cancelará automáticamente."
    )


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

    body_params = await _build_body_params(appt, settings)
    return await deliver_template(
        chatwoot_client,
        appt,
        template,
        body_params,
        _build_fallback_content(body_params),
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
