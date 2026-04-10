"""Consolidated appointment management tool — list, cancel, reschedule.

Single tool that replaces the three separate appointment management tools
(list_customer_appointments, cancel_appointment, reschedule_appointment) with
a unified interface via an `action` parameter.

This tool delegates the heavy lifting to existing services:
- list   → agent.services.appointment_query_service (internal helpers)
- cancel → agent.services.cancellation_service.execute_cancellation
- reschedule → agent.services.reschedule_service.execute_reschedule (in-place UPDATE)

Usage:
    from agent.tools.manage_appointments_tool import manage_appointments
    # Used directly as a @tool in the new 4-tool architecture
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Spanish weekday and month names — used for display (mirrors patterns across codebase)
_WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS_ES = [
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
    """Format a datetime to a Spanish date string like 'martes 1 de abril'."""
    return f"{_WEEKDAYS_ES[dt.weekday()]} {dt.day} de {_MONTHS_ES[dt.month - 1]}"


# ============================================================================
# Pydantic schema
# ============================================================================


class ManageAppointmentsSchema(BaseModel):
    """Input schema for manage_appointments tool."""

    action: Literal["list", "cancel", "reschedule"] = Field(
        description=(
            "Acción a ejecutar: "
            "'list' para ver las próximas citas del cliente, "
            "'cancel' para cancelar una cita existente, "
            "'reschedule' para reagendar una cita a nueva fecha/hora."
        )
    )
    customer_phone: str = Field(
        description="Teléfono del cliente en formato E.164 (ej. +34612345678)"
    )
    appointment_id: str | None = Field(
        default=None,
        description=(
            "UUID de la cita a gestionar. "
            "Requerido para las acciones 'cancel' y 'reschedule'."
        ),
    )
    new_date: str | None = Field(
        default=None,
        description=(
            "Nueva fecha para reagendar, en español natural o ISO. "
            "Ejemplos: 'mañana', 'viernes', '15 de abril', '2026-04-15'. "
            "Requerido para la acción 'reschedule'."
        ),
    )
    new_time: str | None = Field(
        default=None,
        description=(
            "Nueva hora para reagendar en formato HH:MM (ej. '10:00', '16:30'). "
            "Si se omite en 'reschedule', el servicio buscará el primer slot disponible "
            "para la fecha indicada."
        ),
    )
    reason: str | None = Field(
        default=None,
        description="Motivo de cancelación o reagendamiento (opcional, para registro interno).",
    )


# ============================================================================
# Internal helpers
# ============================================================================


async def _list_appointments(customer_phone: str) -> dict[str, Any]:
    """
    Return upcoming appointments for *customer_phone* as a structured dict.

    Delegates to appointment_query_service internals to preserve the same
    rich output (appointment ID, ISO timestamps, hours_until, etc.) that the
    APPOINTMENT_MANAGEMENT mode's pre-resolvers and the LLM depend on.
    """
    try:
        from agent.services.appointment_query_service import (
            _get_customer_by_phone,
            _get_service_names,
            _get_upcoming_appointments,
        )

        customer = await _get_customer_by_phone(customer_phone)
        if not customer:
            return {
                "success": True,
                "error_code": None,
                "appointments": [],
                "count": 0,
                "message": "No tienes citas programadas. ¿Quieres reservar una?",
            }

        appointments = await _get_upcoming_appointments(customer.id, limit=5)

        if not appointments:
            return {
                "success": True,
                "error_code": None,
                "appointments": [],
                "count": 0,
                "message": "No tienes citas próximas. ¿Quieres reservar una?",
            }

        now = datetime.now(MADRID_TZ)
        items: list[dict[str, Any]] = []

        for idx, appt in enumerate(appointments, start=1):
            appt_time = appt.start_time.astimezone(MADRID_TZ)
            hours_until = (appt_time - now).total_seconds() / 3600
            stylist_name = appt.stylist.name if appt.stylist else "tu estilista"
            service_names = await _get_service_names(appt.service_ids or [])

            items.append(
                {
                    "index": idx,
                    "id": str(appt.id),
                    "date_display": _format_date_spanish(appt_time),
                    "time_display": appt_time.strftime("%H:%M"),
                    "stylist_name": stylist_name,
                    "stylist_id": str(appt.stylist.id) if appt.stylist else None,
                    "service_name": service_names,
                    "status": (
                        appt.status.value
                        if hasattr(appt.status, "value")
                        else str(appt.status)
                    ),
                    "start_time_iso": appt_time.isoformat(),
                    "hours_until": round(hours_until, 1),
                }
            )

        count = len(items)
        message = (
            f"Encontré {count} cita{'s' if count != 1 else ''} "
            f"próxima{'s' if count != 1 else ''}:"
        )

        logger.info(
            "manage_appointments[list]: found %d appointments for %s",
            count,
            customer_phone,
        )

        return {
            "success": True,
            "error_code": None,
            "appointments": items,
            "count": count,
            "message": message,
        }

    except Exception as exc:
        logger.exception("Error in _list_appointments for %s: %s", customer_phone, exc)
        return {
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "appointments": [],
            "count": 0,
            "message": "No pude consultar tus citas en este momento. Inténtalo de nuevo.",
        }


async def _cancel_appointment(
    customer_phone: str,
    appointment_id: str,
    reason: str | None,
) -> dict[str, Any]:
    """
    Cancel *appointment_id* after verifying it belongs to *customer_phone*.

    Validates ownership via cancellation_service (which loads the appointment
    with its customer relation and checks the 48h window policy).
    GCal deletion and admin notification are handled inside execute_cancellation.
    """
    if not appointment_id:
        return {
            "success": False,
            "error_code": "APPOINTMENT_ID_REQUIRED",
            "appointment_id": None,
            "within_window": False,
            "hours_until": None,
            "message": "Necesito el ID de la cita para cancelarla.",
        }

    # Validate UUID format early — cleaner error than a DB exception
    try:
        appt_uuid = UUID(appointment_id)
    except (ValueError, AttributeError) as exc:
        logger.error(
            "manage_appointments[cancel]: invalid UUID '%s': %s", appointment_id, exc
        )
        return {
            "success": False,
            "error_code": "APPOINTMENT_NOT_FOUND",
            "appointment_id": appointment_id,
            "within_window": False,
            "hours_until": None,
            "message": "El ID de la cita no es válido.",
        }

    try:
        from agent.services.cancellation_service import (
            execute_cancellation,
            get_customer_by_phone,
            get_cancellable_appointments,
        )

        # Ownership check: verify appointment belongs to this customer
        customer = await get_customer_by_phone(customer_phone)
        if not customer:
            return {
                "success": False,
                "error_code": "CUSTOMER_NOT_FOUND",
                "appointment_id": appointment_id,
                "within_window": False,
                "hours_until": None,
                "message": "No encontré tu perfil de cliente.",
            }

        # Confirm the appointment exists in the customer's cancellable list
        customer_appointments = await get_cancellable_appointments(customer.id)
        owned = any(str(a.id) == appointment_id for a in customer_appointments)
        if not owned:
            logger.warning(
                "manage_appointments[cancel]: appointment %s not owned by phone %s",
                appointment_id,
                customer_phone,
            )
            return {
                "success": False,
                "error_code": "APPOINTMENT_NOT_OWNED",
                "appointment_id": appointment_id,
                "within_window": False,
                "hours_until": None,
                "message": "No encontré esa cita en tu historial.",
            }

        # Delegate actual cancellation (window check + DB update + GCal + notification)
        result = await execute_cancellation(appt_uuid, reason=reason, conversation_id=None)

        if result.success:
            response_text = (
                result.response_text or "Tu cita ha sido cancelada correctamente."
            )
            logger.info(
                "manage_appointments[cancel]: appointment %s cancelled", appointment_id
            )
            return {
                "success": True,
                "error_code": None,
                "appointment_id": appointment_id,
                "within_window": False,
                "hours_until": None,
                "message": response_text,
            }
        else:
            logger.warning(
                "manage_appointments[cancel]: failed for %s — within_window=%s",
                appointment_id,
                result.within_window,
            )
            error_code = "CANCEL_TOO_LATE" if result.within_window else "INTERNAL_ERROR"
            return {
                "success": False,
                "error_code": error_code,
                "appointment_id": appointment_id,
                "within_window": result.within_window,
                "hours_until": result.hours_until_appointment,
                "message": (
                    result.error_message or "No se pudo cancelar la cita."
                ),
            }

    except Exception as exc:
        logger.exception(
            "Error in _cancel_appointment for %s: %s", appointment_id, exc
        )
        return {
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "appointment_id": appointment_id,
            "within_window": False,
            "hours_until": None,
            "message": "Ocurrió un error al cancelar la cita. Por favor, inténtalo de nuevo.",
        }


async def _reschedule_appointment(
    customer_phone: str,
    appointment_id: str,
    new_date: str,
    new_time: str | None,
    reason: str | None,  # noqa: ARG001 — reserved for future audit logging
) -> dict[str, Any]:
    """
    Reschedule *appointment_id* to *new_date* + *new_time* for *customer_phone*.

    Steps:
    1. Validate ownership and eligibility via reschedule_service.
    2. Parse the natural-language date via parse_natural_date().
    3. Build the new datetime; if new_time is missing, use the first available
       slot for that date (via get_available_slots).
    4. Execute in-place UPDATE via reschedule_service.execute_reschedule().
    """
    if not appointment_id:
        return {
            "success": False,
            "error_code": "APPOINTMENT_ID_REQUIRED",
            "appointment_id": None,
            "old_start_time": None,
            "new_start_time": None,
            "within_window": False,
            "slot_taken": False,
            "message": "Necesito el ID de la cita para reagendarla.",
        }

    if not new_date:
        return {
            "success": False,
            "error_code": "RESCHEDULE_PARAMS_REQUIRED",
            "appointment_id": appointment_id,
            "old_start_time": None,
            "new_start_time": None,
            "within_window": False,
            "slot_taken": False,
            "message": "Necesito la nueva fecha para reagendar la cita.",
        }

    # Validate UUID format
    try:
        appt_uuid = UUID(appointment_id)
    except (ValueError, AttributeError) as exc:
        logger.error(
            "manage_appointments[reschedule]: invalid UUID '%s': %s",
            appointment_id,
            exc,
        )
        return {
            "success": False,
            "error_code": "APPOINTMENT_NOT_FOUND",
            "appointment_id": appointment_id,
            "old_start_time": None,
            "new_start_time": None,
            "within_window": False,
            "slot_taken": False,
            "message": "El ID de la cita no es válido.",
        }

    try:
        from agent.services.reschedule_service import (
            validate_reschedule_eligibility,
            execute_reschedule,
            find_reschedule_slots,
        )
        from agent.utils.date_parser import parse_natural_date, DateParseError
        from agent.services.availability_service import get_available_slots
        from agent.validators.transaction_validators import validate_3_day_rule

        # 1. Validate eligibility (ownership + status + 48h window)
        eligibility = await validate_reschedule_eligibility(
            appointment_id=appt_uuid,
            customer_phone=customer_phone,
        )

        if not eligibility.eligible:
            error_code = "CANCEL_TOO_LATE" if eligibility.within_window else "APPOINTMENT_NOT_OWNED"
            logger.warning(
                "manage_appointments[reschedule]: not eligible for %s — %s",
                appointment_id,
                eligibility.reason,
            )
            return {
                "success": False,
                "error_code": error_code,
                "appointment_id": appointment_id,
                "old_start_time": None,
                "new_start_time": None,
                "within_window": eligibility.within_window,
                "slot_taken": False,
                "message": eligibility.reason,
            }

        # 2. Parse the natural date expression
        try:
            parsed_date = parse_natural_date(new_date)
        except DateParseError as exc:
            logger.warning(
                "manage_appointments[reschedule]: could not parse date '%s': %s",
                new_date,
                exc,
            )
            return {
                "success": False,
                "error_code": "RESCHEDULE_PARAMS_REQUIRED",
                "appointment_id": appointment_id,
                "old_start_time": None,
                "new_start_time": None,
                "within_window": False,
                "slot_taken": False,
                "message": (
                    f"No pude entender la fecha '{new_date}'. "
                    "Por favor, indicá una fecha como 'viernes', '15 de abril', o '2026-04-15'."
                ),
            }

        # 2b. Enforce 3-day minimum advance booking rule
        three_day_check = await validate_3_day_rule(parsed_date)
        if not three_day_check["valid"]:
            return {
                "success": False,
                "error_code": "MINIMUM_DAYS_RULE",
                "appointment_id": appointment_id,
                "old_start_time": None,
                "new_start_time": None,
                "within_window": False,
                "slot_taken": False,
                "message": three_day_check["error_message"],
            }

        # 3. Build new datetime
        if new_time:
            try:
                hour, minute = map(int, new_time.split(":"))
                new_start = parsed_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except (ValueError, AttributeError) as exc:
                logger.warning(
                    "manage_appointments[reschedule]: invalid new_time '%s': %s",
                    new_time,
                    exc,
                )
                return {
                    "success": False,
                    "error_code": "RESCHEDULE_PARAMS_REQUIRED",
                    "appointment_id": appointment_id,
                    "old_start_time": None,
                    "new_start_time": None,
                    "within_window": False,
                    "slot_taken": False,
                    "message": (
                        f"La hora '{new_time}' no tiene un formato válido. "
                        "Usa el formato HH:MM (ej. '10:00' o '16:30')."
                    ),
                }
        else:
            # No time specified → find the first available slot for this stylist and date
            appointment = eligibility.appointment
            if appointment is None:
                return {
                    "success": False,
                    "error_code": "APPOINTMENT_NOT_FOUND",
                    "appointment_id": appointment_id,
                    "old_start_time": None,
                    "new_start_time": None,
                    "within_window": False,
                    "slot_taken": False,
                    "message": "No se encontró la cita. Por favor, inténtalo de nuevo.",
                }

            slots = await get_available_slots(
                stylist_id=appointment.stylist_id,
                target_date=parsed_date.date(),
                service_duration_minutes=appointment.duration_minutes,
            )

            if not slots:
                logger.info(
                    "manage_appointments[reschedule]: no slots for %s on %s",
                    appointment_id,
                    parsed_date.date(),
                )
                date_display = _format_date_spanish(parsed_date)
                return {
                    "success": False,
                    "error_code": "NO_SLOTS",
                    "appointment_id": appointment_id,
                    "old_start_time": None,
                    "new_start_time": None,
                    "within_window": False,
                    "slot_taken": False,
                    "message": (
                        f"No hay horarios disponibles el {date_display}. "
                        "¿Quieres intentar con otra fecha?"
                    ),
                }

            # Use the first available (already sorted by adjacent_priority then time)
            first_slot_dt_str = slots[0]["full_datetime"]
            new_start = datetime.fromisoformat(first_slot_dt_str)

        # Ensure new_start is timezone-aware (default to Madrid TZ if naive)
        if new_start.tzinfo is None:
            new_start = new_start.replace(tzinfo=MADRID_TZ)

        # 4. Execute the in-place reschedule
        result = await execute_reschedule(
            appointment_id=appt_uuid,
            new_start_time=new_start,
            new_stylist_id=None,  # keep same stylist
        )

        if result.success:
            new_iso = new_start.isoformat()
            date_display = _format_date_spanish(new_start)
            time_display = new_start.strftime("%H:%M")
            response_text = (
                f"Tu cita ha sido reagendada para el {date_display} a las {time_display}."
            )
            old_iso = (
                result.old_start_time.isoformat() if result.old_start_time else None
            )
            logger.info(
                "manage_appointments[reschedule]: appointment %s rescheduled to %s",
                appointment_id,
                new_iso,
            )
            return {
                "success": True,
                "error_code": None,
                "appointment_id": appointment_id,
                "old_start_time": old_iso,
                "new_start_time": new_iso,
                "within_window": False,
                "slot_taken": False,
                "message": response_text,
            }
        else:
            error_code = (
                "CANCEL_TOO_LATE"
                if result.within_window
                else ("NO_SLOTS" if result.slot_taken else "INTERNAL_ERROR")
            )
            logger.warning(
                "manage_appointments[reschedule]: failed for %s — within_window=%s slot_taken=%s",
                appointment_id,
                result.within_window,
                result.slot_taken,
            )
            return {
                "success": False,
                "error_code": error_code,
                "appointment_id": appointment_id,
                "old_start_time": None,
                "new_start_time": new_start.isoformat(),
                "within_window": result.within_window,
                "slot_taken": result.slot_taken,
                "message": result.error or "No se pudo reagendar la cita.",
            }

    except Exception as exc:
        logger.exception(
            "Error in _reschedule_appointment for %s: %s", appointment_id, exc
        )
        return {
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "appointment_id": appointment_id,
            "old_start_time": None,
            "new_start_time": None,
            "within_window": False,
            "slot_taken": False,
            "message": "Ocurrió un error al reagendar la cita. Por favor, inténtalo de nuevo.",
        }


# ============================================================================
# Public tool
# ============================================================================


@tool(args_schema=ManageAppointmentsSchema)
async def manage_appointments(
    action: Literal["list", "cancel", "reschedule"],
    customer_phone: str,
    appointment_id: str | None = None,
    new_date: str | None = None,
    new_time: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """
    Gestiona las citas de un cliente: listar, cancelar o reagendar.

    Acciones disponibles:
    - 'list': Devuelve las próximas citas del cliente con ID, fecha, hora, estilista y servicios.
    - 'cancel': Cancela una cita específica (requiere appointment_id). Solo ejecutar tras
      confirmación explícita del cliente. Verifica la política de 48h de antelación.
    - 'reschedule': Reagenda una cita a nueva fecha/hora (requiere appointment_id y new_date).
      Solo ejecutar tras confirmación explícita del cliente.

    Códigos de error en la respuesta:
    - CUSTOMER_NOT_FOUND: el teléfono no corresponde a ningún cliente registrado
    - APPOINTMENT_ID_REQUIRED: se llamó cancel/reschedule sin appointment_id
    - APPOINTMENT_NOT_FOUND: el appointment_id no existe en la base de datos
    - APPOINTMENT_NOT_OWNED: la cita pertenece a otro cliente
    - CANCEL_TOO_LATE: se intenta cancelar/reagendar dentro de la ventana de política (48h)
    - RESCHEDULE_PARAMS_REQUIRED: se llamó reschedule sin new_date o con formato inválido
    - NO_SLOTS: no hay disponibilidad para la nueva fecha/hora solicitada
    """
    logger.info(
        "manage_appointments: action=%s phone=%s appointment_id=%s new_date=%s new_time=%s",
        action,
        customer_phone,
        appointment_id,
        new_date,
        new_time,
    )

    if action == "list":
        return await _list_appointments(customer_phone)

    elif action == "cancel":
        if not appointment_id:
            return {
                "success": False,
                "error_code": "APPOINTMENT_ID_REQUIRED",
                "appointment_id": None,
                "within_window": False,
                "hours_until": None,
                "message": "Necesito el ID de la cita para cancelarla.",
            }
        return await _cancel_appointment(customer_phone, appointment_id, reason)

    elif action == "reschedule":
        if not appointment_id:
            return {
                "success": False,
                "error_code": "APPOINTMENT_ID_REQUIRED",
                "appointment_id": None,
                "old_start_time": None,
                "new_start_time": None,
                "within_window": False,
                "slot_taken": False,
                "message": "Necesito el ID de la cita para reagendarla.",
            }
        if not new_date:
            return {
                "success": False,
                "error_code": "RESCHEDULE_PARAMS_REQUIRED",
                "appointment_id": appointment_id,
                "old_start_time": None,
                "new_start_time": None,
                "within_window": False,
                "slot_taken": False,
                "message": "Necesito la nueva fecha para reagendar la cita.",
            }
        return await _reschedule_appointment(
            customer_phone, appointment_id, new_date, new_time, reason
        )

    # Should never reach here — Literal type + Pydantic prevent unknown actions
    logger.error("manage_appointments: unknown action '%s'", action)
    return {
        "success": False,
        "error_code": "INTERNAL_ERROR",
        "message": f"Acción desconocida: '{action}'.",
    }
