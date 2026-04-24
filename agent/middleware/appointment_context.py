"""AppointmentContextMiddleware — inject upcoming appointments into system prompt.

Hook: awrap_model_call (mirrors CustomerResolveMiddleware pattern)

Algorithm:
1. Read state.customer_id — if absent, pass through.
2. Fetch upcoming appointments (PENDING/CONFIRMED, start_time > now, LIMIT 5).
3. If none, pass through.
4. Build ## Citas próximas block and append to system_message.
5. Call handler with overridden request.

On any DB/query error: log WARNING, pass through (graceful degrade).

Must run AFTER CustomerResolveMiddleware (reads customer_id it sets).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import ClassVar
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from shared.date_format import format_date_spanish as _format_date_spanish

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")


def _format_relative(past_dt: datetime, now: datetime) -> str:
    """Format a past datetime relative to now in natural Spanish.

    Returns strings like 'hace 5 minutos', 'hace 3h', 'hace 2 días'.
    Assumes past_dt <= now.
    """
    delta = now - past_dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return "hace unos segundos"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"hace {minutes} minutos" if minutes != 1 else "hace 1 minuto"
    hours = minutes // 60
    if hours < 24:
        return f"hace {hours}h"
    days = hours // 24
    return f"hace {days} días" if days != 1 else "hace 1 día"


def _format_lifecycle_line(appt, now: datetime) -> str:
    """Render 'Estado: <STATUS> · confirmación <...> · recordatorio <...>' line."""
    from database.models import AppointmentStatus

    status_label = {
        AppointmentStatus.PENDING: "PENDIENTE",
        AppointmentStatus.CONFIRMED: "CONFIRMADA",
    }.get(appt.status, str(appt.status.name if hasattr(appt.status, "name") else appt.status))

    confirmation_sent_at = getattr(appt, "confirmation_sent_at", None)
    if confirmation_sent_at is None:
        confirmation_part = "confirmación pendiente"
    else:
        confirmation_part = f"confirmación pedida {_format_relative(confirmation_sent_at, now)}"

    reminder_sent_at = getattr(appt, "reminder_sent_at", None)
    if reminder_sent_at is None:
        reminder_part = "recordatorio pendiente"
    else:
        reminder_part = f"recordatorio enviado {_format_relative(reminder_sent_at, now)}"

    return f"Estado: {status_label} · {confirmation_part} · {reminder_part}"


async def _get_service_names_for_middleware(service_ids: list[UUID]) -> str:
    """Fetch service names joined with ' + '. Returns 'servicios' on error."""
    if not service_ids:
        return "servicios"
    try:
        from sqlalchemy import select

        from database.connection import get_async_session
        from database.models import Service

        async with get_async_session() as session:
            result = await session.execute(select(Service).where(Service.id.in_(service_ids)))
            services = list(result.scalars().all())
            if services:
                return " + ".join(s.name for s in services)
            return "servicios"
    except Exception:
        return "servicios"


async def _fetch_upcoming_appointments(customer_id: UUID, limit: int = 5) -> list:
    """
    Query upcoming PENDING/CONFIRMED appointments for customer_id.

    Returns a list of Appointment ORM objects (with stylist eager-loaded).
    Returns empty list on any DB error (caller handles graceful degrade).
    """
    from sqlalchemy import and_, select
    from sqlalchemy.orm import selectinload

    from database.connection import get_async_session
    from database.models import Appointment, AppointmentStatus

    now = datetime.now(MADRID_TZ)

    async with get_async_session() as session:
        result = await session.execute(
            select(Appointment)
            .options(selectinload(Appointment.stylist))
            .where(
                and_(
                    Appointment.customer_id == customer_id,
                    Appointment.status.in_(
                        [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]
                    ),
                    Appointment.start_time > now,
                )
            )
            .order_by(Appointment.start_time.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


def _format_block(appointments: list) -> str:
    """Build the <upcoming_appointments> XML slot from a list of Appointment objects.

    Note: service_names must have been pre-fetched by the caller (async context).
    This helper is called with pre-fetched _service_names attribute per appointment.
    """
    now = datetime.now(MADRID_TZ)
    lines = []
    for appt in appointments:
        appt_time = appt.start_time.astimezone(MADRID_TZ)
        fecha = _format_date_spanish(appt_time)
        hora = appt_time.strftime("%H:%M")
        stylist_name = appt.stylist.name if appt.stylist else "estilista"
        service_names = getattr(appt, "_injected_service_names", "servicios")
        lifecycle = _format_lifecycle_line(appt, now)
        lines.append(
            f"- ID: {appt.id}\n"
            f"  Fecha: {fecha}\n"
            f"  Hora: {hora}\n"
            f"  Estilista: {stylist_name}\n"
            f"  Servicio: {service_names}\n"
            f"  {lifecycle}"
        )
    body = "\n".join(lines)
    return f"<upcoming_appointments>\n{body}\n</upcoming_appointments>"


class AppointmentContextMiddleware(AgentMiddleware):
    """Inject upcoming appointments into the system prompt each model call turn.

    Async-only: appointment and service lookups are async SQLAlchemy queries.
    A sync variant would require a duplicate sync DB path that the runtime
    never exercises. Opt out of the parity guardrail.
    """

    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state or {}
        customer_id = state.get("customer_id")

        if not customer_id:
            return await handler(request)

        try:
            appointments = await _fetch_upcoming_appointments(customer_id, limit=5)
        except Exception as exc:
            logger.warning(
                "AppointmentContextMiddleware: DB fetch failed for customer_id=%s: %s",
                customer_id,
                exc,
            )
            return await handler(request)

        if not appointments:
            return await handler(request)

        # Pre-fetch service names for each appointment (async, before _format_block)
        for appt in appointments:
            service_names = await _get_service_names_for_middleware(
                getattr(appt, "service_ids", [])
            )
            appt._injected_service_names = service_names

        slot = _format_block(appointments)
        new_state = {**state, "_slot_upcoming_appointments": slot}
        modified_request = request.override(state=new_state)

        logger.info(
            "AppointmentContextMiddleware: injected %d appointments for customer_id=%s",
            len(appointments),
            customer_id,
        )

        return await handler(modified_request)
