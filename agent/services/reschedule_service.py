"""
Appointment reschedule service — Handles customer-initiated reschedules.

This service processes customer requests to reschedule their appointments:
- validate_reschedule_eligibility: Check if an appointment can be rescheduled
  (ownership, status, 48h window)
- find_reschedule_slots: Get available slots for the new date
- execute_reschedule: In-place UPDATE of start_time/stylist — single DB transaction

Architecture:
- In-place UPDATE (not cancel + rebook) — preserves appointment ID and avoids limit checks
- 48h window enforced deterministically (Python datetime math, not LLM)
- GCal sync is fire-and-forget — DB commit never rolls back on GCal failure
- Follows the same error handling and logging patterns as cancellation_service.py
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from agent.services.availability_service import check_slot_availability, get_available_slots
from agent.services.gcal_push_service import update_appointment_in_gcal
from database.connection import get_async_session
from database.models import (
    Appointment,
    AppointmentStatus,
    Service,
)
from shared.settings_service import get_settings_service

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Spanish weekday and month names for date formatting (mirrors cancellation_service.py)
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def _format_date_spanish(dt: datetime) -> str:
    """Format datetime to Spanish date string (e.g. 'viernes 20 de diciembre')."""
    return f"{WEEKDAYS_ES[dt.weekday()]} {dt.day} de {MONTHS_ES[dt.month - 1]}"


async def _get_cancellation_window_hours() -> int:
    """
    Get configurable reschedule/cancellation window from database settings.

    Reuses the same 'cancellation_window_hours' setting as cancellation_service
    (both operations share the same advance-notice policy).

    Returns:
        Number of hours before appointment that rescheduling is allowed.
        Default: 48 hours.
    """
    try:
        settings_service = await get_settings_service()
        return await settings_service.get("cancellation_window_hours", 48)
    except Exception as e:
        logger.warning(f"Could not load cancellation_window_hours setting: {e}. Using default 48h.")
        return 48


async def _get_service_names(service_ids: list[UUID]) -> str:
    """Get comma-separated service names from service IDs."""
    if not service_ids:
        return "servicios"
    try:
        async with get_async_session() as session:
            result = await session.execute(select(Service).where(Service.id.in_(service_ids)))
            services = list(result.scalars().all())
            if services:
                return " + ".join([s.name for s in services])
            return "servicios"
    except Exception:
        return "servicios"


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RescheduleEligibility:
    """
    Result of a reschedule eligibility check.

    Attributes:
        eligible: True if the appointment can be rescheduled.
        appointment: The Appointment object (populated when eligible=True or for
            within-window diagnostics).
        reason: Human-readable Spanish reason when eligible=False.
        hours_until: Decimal hours until the appointment start time.
        within_window: True when blocked specifically because of the 48h policy.
    """

    eligible: bool
    appointment: Appointment | None = None
    reason: str = ""
    hours_until: float = 0.0
    within_window: bool = False


@dataclass
class RescheduleResult:
    """
    Result of executing a reschedule operation.

    Attributes:
        success: True if the appointment was updated in the database.
        appointment_id: UUID of the affected appointment.
        old_start_time: Original start time before the update.
        new_start_time: New start time after the update.
        new_stylist_id: The stylist UUID after the update (may be unchanged).
            Reserved for admin-panel callers. The chat tool ``manage_appointments``
            does NOT expose this parameter.
        error: Spanish-language error message when success=False.
        within_window: True when blocked by the 48h advance-notice rule.
        slot_taken: True when the requested slot is no longer available.
    """

    success: bool
    appointment_id: UUID | None = None
    old_start_time: datetime | None = None
    new_start_time: datetime | None = None
    new_stylist_id: UUID | None = None
    error: str | None = None
    within_window: bool = False
    slot_taken: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


async def validate_reschedule_eligibility(
    appointment_id: UUID,
    customer_phone: str,
) -> RescheduleEligibility:
    """
    Check whether a customer may reschedule the given appointment.

    Validates:
    1. Appointment exists.
    2. Ownership — appointment's customer phone matches ``customer_phone``.
    3. Status is PENDING or CONFIRMED (not CANCELLED/COMPLETED/NO_SHOW).
    4. Hours until appointment exceeds the cancellation window (default 48h).

    Args:
        appointment_id: UUID of the appointment to reschedule.
        customer_phone: E.164 phone number of the requesting customer.

    Returns:
        RescheduleEligibility with eligible=True when all checks pass.
        When eligible=False, ``reason`` contains a human-readable Spanish message
        and ``within_window`` / ``hours_until`` are set appropriately.
    """
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(Appointment)
                .options(
                    selectinload(Appointment.customer),
                    selectinload(Appointment.stylist),
                )
                .where(Appointment.id == appointment_id)
            )
            appointment = result.scalars().first()

            if not appointment:
                return RescheduleEligibility(
                    eligible=False,
                    reason="No se encontró la cita. Por favor, intenta de nuevo.",
                )

            # 1. Ownership check
            if not appointment.customer or appointment.customer.phone != customer_phone:
                logger.warning(
                    f"Reschedule ownership mismatch: appointment {appointment_id} "
                    f"does not belong to phone {customer_phone}"
                )
                return RescheduleEligibility(
                    eligible=False,
                    reason="No se encontró la cita. Por favor, intenta de nuevo.",
                )

            # 2. Status check
            reschedulable_statuses = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}
            if appointment.status not in reschedulable_statuses:
                status_display = {
                    AppointmentStatus.CANCELLED: "cancelada",
                    AppointmentStatus.COMPLETED: "completada",
                    AppointmentStatus.NO_SHOW: "marcada como no presentado",
                }.get(appointment.status, str(appointment.status))
                return RescheduleEligibility(
                    eligible=False,
                    appointment=appointment,
                    reason=(
                        f"Esta cita ya fue {status_display} y no puede reagendarse. "
                        f"¿Te gustaría reservar una nueva cita?"
                    ),
                )

            # 3. 48h window check
            window_hours = await _get_cancellation_window_hours()
            now = datetime.now(MADRID_TZ)
            appt_time = appointment.start_time.astimezone(MADRID_TZ)
            hours_until = (appt_time - now).total_seconds() / 3600

            if hours_until <= window_hours:
                fecha = _format_date_spanish(appt_time)
                hora = appt_time.strftime("%H:%M")
                return RescheduleEligibility(
                    eligible=False,
                    appointment=appointment,
                    reason=(
                        f"Tu cita del {fecha} a las {hora} es en {int(hours_until)} horas. "
                        f"Solo puedes reagendar con al menos {window_hours} horas de antelación. "
                        f"Si realmente necesitas cambiarla, puedo conectarte con el equipo."
                    ),
                    hours_until=hours_until,
                    within_window=True,
                )

            return RescheduleEligibility(
                eligible=True,
                appointment=appointment,
                hours_until=hours_until,
            )

    except Exception as e:
        logger.exception(
            f"Error validating reschedule eligibility for appointment {appointment_id}: {e}"
        )
        return RescheduleEligibility(
            eligible=False,
            reason="Ha ocurrido un error al verificar la cita. Por favor, intenta de nuevo.",
        )


async def find_reschedule_slots(
    appointment_id: UUID,
    target_date: datetime,
    stylist_id: UUID | None = None,
) -> list[dict]:
    """
    Get available slots for rescheduling an appointment to a new date.

    Delegates to ``availability_service.get_available_slots()`` and excludes
    the current appointment's own slot (to avoid showing it as "unavailable").

    Args:
        appointment_id: UUID of the appointment being rescheduled. Used to load
            duration and current start_time for exclusion.
        target_date: The date the customer wants to reschedule to
            (timezone-aware). Only the date portion is used; time is ignored.
        stylist_id: If provided, limits availability to that stylist. When None,
            the existing stylist is kept.

    Returns:
        List of slot dicts compatible with ``check_availability`` tool output.
        Empty list when no slots are available or on error.
    """
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(Appointment).where(Appointment.id == appointment_id)
            )
            appointment = result.scalars().first()

            if not appointment:
                logger.warning(f"find_reschedule_slots: appointment {appointment_id} not found")
                return []

            effective_stylist_id = stylist_id or appointment.stylist_id
            duration = appointment.duration_minutes
            current_start = appointment.start_time

        # Delegate to availability service
        slots = await get_available_slots(
            stylist_id=effective_stylist_id,
            date=target_date.date() if hasattr(target_date, "date") else target_date,
            service_duration_minutes=duration,
        )

        # Exclude the appointment's own current slot so it doesn't appear
        # as "taken" in the availability list
        slots = [s for s in slots if s.get("start_time") != current_start.isoformat()]

        return slots

    except Exception as e:
        logger.exception(f"Error finding reschedule slots for appointment {appointment_id}: {e}")
        return []


async def execute_reschedule(
    appointment_id: UUID,
    new_start_time: datetime,
    new_stylist_id: UUID | None = None,
) -> RescheduleResult:
    """
    Execute an appointment reschedule as an in-place UPDATE.

    Steps:
    1. Load appointment with relations.
    2. Re-validate 48h window (time may have passed since eligibility check).
    3. Re-validate slot availability INSIDE the same DB session (race condition guard).
    4. UPDATE start_time, stylist_id (if provided), updated_at.
    5. Commit DB.
    6. Fire-and-forget ``update_appointment_in_gcal()`` — DB commit is never
       rolled back on GCal failure; failures are logged at WARNING level.
    7. Return RescheduleResult with success=True.

    Args:
        appointment_id: UUID of the appointment to reschedule.
        new_start_time: New start time (timezone-aware).
        new_stylist_id: New stylist UUID. When None, the existing stylist is kept.
            Reserved for admin-panel callers. The chat tool ``manage_appointments``
            does NOT expose this parameter.

    Returns:
        RescheduleResult with success=True on DB commit, success=False otherwise.
        ``slot_taken=True`` indicates a race condition (slot gone between check and update).
        ``within_window=True`` indicates the 48h window was violated.
        ``error`` contains a human-readable Spanish message on failure.
    """
    try:
        async with get_async_session() as session:
            # Load appointment with eager-loaded relations for GCal call later
            result = await session.execute(
                select(Appointment)
                .options(
                    selectinload(Appointment.customer),
                    selectinload(Appointment.stylist),
                )
                .where(Appointment.id == appointment_id)
            )
            appointment = result.scalars().first()

            if not appointment:
                return RescheduleResult(
                    success=False,
                    error="No se encontró la cita. Por favor, intenta de nuevo.",
                )

            # Re-validate status
            reschedulable_statuses = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}
            if appointment.status not in reschedulable_statuses:
                return RescheduleResult(
                    success=False,
                    appointment_id=appointment.id,
                    error="Esta cita ya no puede reagendarse. ¿Te gustaría reservar una nueva cita?",
                )

            # Re-validate 48h window (time may have passed since eligibility was checked)
            window_hours = await _get_cancellation_window_hours()
            now = datetime.now(MADRID_TZ)
            appt_time = appointment.start_time.astimezone(MADRID_TZ)
            hours_until = (appt_time - now).total_seconds() / 3600

            if hours_until <= window_hours:
                fecha = _format_date_spanish(appt_time)
                hora = appt_time.strftime("%H:%M")
                return RescheduleResult(
                    success=False,
                    appointment_id=appointment.id,
                    within_window=True,
                    error=(
                        f"Tu cita del {fecha} a las {hora} ya no puede reagendarse por este medio "
                        f"(mínimo {window_hours}h de antelación). "
                        f"Por favor, contacta directamente con el equipo."
                    ),
                )

            # Determine effective stylist and duration for availability check
            effective_stylist_id = new_stylist_id or appointment.stylist_id
            duration = appointment.duration_minutes

            # Re-validate slot availability INSIDE the same DB session
            # (guard against race conditions between eligibility check and update)
            slot_check = await check_slot_availability(
                stylist_id=effective_stylist_id,
                start_time=new_start_time,
                duration_minutes=duration,
            )

            if not slot_check.get("available"):
                conflict = slot_check.get(
                    "conflict_details", "El horario solicitado no está disponible"
                )
                return RescheduleResult(
                    success=False,
                    appointment_id=appointment.id,
                    slot_taken=True,
                    error=(
                        f"El horario ya no está disponible: {conflict}. "
                        f"¿Quieres que busquemos otro horario?"
                    ),
                )

            # Snapshot old values for the result and GCal call
            old_start_time = appointment.start_time
            old_gcal_event_id = appointment.google_calendar_event_id
            old_stylist_id = appointment.stylist_id

            # Perform in-place UPDATE
            appointment.start_time = new_start_time
            if new_stylist_id is not None:
                appointment.stylist_id = new_stylist_id
            appointment.updated_at = now

            await session.commit()

            logger.info(
                f"Appointment {appointment_id} rescheduled | "
                f"old_start={old_start_time.isoformat()} | "
                f"new_start={new_start_time.isoformat()} | "
                f"stylist_changed={new_stylist_id is not None}"
            )

        # ── Fire-and-forget GCal update (OUTSIDE the DB session) ─────────────
        # DB is already committed — GCal failure MUST NOT roll back the update.
        if old_gcal_event_id:
            try:
                customer_name = (
                    appointment.customer.first_name
                    if appointment.customer
                    else appointment.first_name or "Cliente"
                )
                service_names = await _get_service_names(appointment.service_ids)

                await update_appointment_in_gcal(
                    appointment_id=appointment_id,
                    stylist_id=effective_stylist_id,
                    event_id=old_gcal_event_id,
                    customer_name=customer_name,
                    service_names=service_names,
                    start_time=new_start_time,
                    duration_minutes=duration,
                    status=str(appointment.status),
                    customer_phone=(appointment.customer.phone if appointment.customer else None),
                )
                logger.info(f"GCal event updated for rescheduled appointment {appointment_id}")
            except Exception as gcal_error:
                # GCal failure logged but NOT raised — DB commit already succeeded
                logger.warning(
                    f"GCal update failed for rescheduled appointment {appointment_id} "
                    f"(DB already committed): {gcal_error}"
                )

        return RescheduleResult(
            success=True,
            appointment_id=appointment_id,
            old_start_time=old_start_time,
            new_start_time=new_start_time,
            new_stylist_id=effective_stylist_id,
        )

    except Exception as e:
        logger.exception(f"Error rescheduling appointment {appointment_id}: {e}")
        return RescheduleResult(
            success=False,
            appointment_id=appointment_id,
            error="Ha ocurrido un error al reagendar la cita. Por favor, intenta de nuevo.",
        )
