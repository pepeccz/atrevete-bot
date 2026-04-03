"""
Appointment Management Tools — T2, T3, T4.

Three tools for the APPOINTMENT_MANAGEMENT mode:
  - list_customer_appointments: Query upcoming appointments with rich dict output
  - cancel_appointment: Execute a confirmed cancellation (pre-tool gate ensures confirmation)
  - reschedule_appointment: Execute a confirmed reschedule (pre-tool gate ensures confirmation)

Customer phone is injected at construction time via the create_appointment_tools() factory,
following the same closure pattern used across the codebase.

Usage:
    tools = create_appointment_tools(customer_phone=state["customer_phone"])
    # Pass tools list to _run_agentic_loop()
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Spanish weekday and month names for date formatting (consistent with service layer)
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
# T2 — list_customer_appointments
# ============================================================================


class ListCustomerAppointmentsInput(BaseModel):
    """Input schema for list_customer_appointments."""

    limit: int = Field(
        default=5,
        description="Número máximo de citas próximas a devolver",
        ge=1,
        le=20,
    )


async def _list_customer_appointments(limit: int, customer_phone: str) -> dict[str, Any]:
    """
    Return upcoming appointments for *customer_phone* as a structured dict.

    Deviation from task spec: the public `appointment_query_service.get_upcoming_appointments()`
    only returns an aggregated `AppointmentQueryResult` with no individual appointment IDs or
    ISO timestamps.  The APPOINTMENT_MANAGEMENT mode's pre-resolvers and the LLM need
    `id`, `start_time_iso`, `hours_until`, etc. to work correctly.  Therefore this function
    calls the internal `_get_upcoming_appointments` helper (same module, no new DB logic) and
    formats the result directly.  The same session / query logic is reused — no duplication.
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
                "appointments": [],
                "count": 0,
                "message": "No tenés citas programadas. ¿Querés reservar una?",
            }

        appointments = await _get_upcoming_appointments(customer.id, limit)

        if not appointments:
            return {
                "success": True,
                "appointments": [],
                "count": 0,
                "message": "No tenés citas próximas. ¿Querés reservar una?",
            }

        now = datetime.now(MADRID_TZ)
        items: list[dict[str, Any]] = []

        for idx, appt in enumerate(appointments, start=1):
            appt_time = appt.start_time.astimezone(MADRID_TZ)
            hours_until = (appt_time - now).total_seconds() / 3600
            stylist_name = appt.stylist.name if appt.stylist else "tu estilista"
            service_name = await _get_service_names(appt.service_ids or [])

            items.append(
                {
                    "index": idx,
                    "id": str(appt.id),
                    "date_display": _format_date_spanish(appt_time),
                    "time_display": appt_time.strftime("%H:%M"),
                    "stylist_name": stylist_name,
                    "stylist_id": str(appt.stylist.id) if appt.stylist else None,
                    "service_name": service_name,
                    "status": (
                        appt.status.value if hasattr(appt.status, "value") else str(appt.status)
                    ),
                    "start_time_iso": appt_time.isoformat(),
                    "hours_until": round(hours_until, 1),
                }
            )

        count = len(items)
        message = (
            f"Encontré {count} cita{'s' if count != 1 else ''} próxima{'s' if count != 1 else ''}:"
        )

        logger.info(
            "list_customer_appointments: found %d appointments for %s",
            count,
            customer_phone,
        )

        return {
            "success": True,
            "appointments": items,
            "count": count,
            "message": message,
        }

    except Exception as exc:
        logger.exception("Error in _list_customer_appointments: %s", exc)
        return {
            "success": False,
            "appointments": [],
            "count": 0,
            "message": "No pude consultar tus citas en este momento. Intentá de nuevo.",
        }


# ============================================================================
# T3 — cancel_appointment
# ============================================================================


class CancelAppointmentInput(BaseModel):
    """Input schema for cancel_appointment."""

    appointment_id: str = Field(description="UUID de la cita a cancelar")
    reason: str | None = Field(default=None, description="Motivo opcional de cancelación")


async def _cancel_appointment(
    appointment_id: str,
    reason: str | None,
    customer_phone: str,  # noqa: ARG001 — available for audit/logging
) -> dict[str, Any]:
    """
    Execute the cancellation of *appointment_id*.

    IMPORTANT: This tool only executes.  The APPOINTMENT_MANAGEMENT mode's
    `_pre_tool_call` gate ensures the customer has already confirmed the
    cancellation before this function is ever called.
    """
    try:
        appt_uuid = UUID(appointment_id)
    except (ValueError, AttributeError) as exc:
        logger.error("cancel_appointment: invalid UUID '%s': %s", appointment_id, exc)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "El ID de la cita no es válido.",
        }

    try:
        from agent.services.cancellation_service import execute_cancellation

        result = await execute_cancellation(appt_uuid, reason=reason, conversation_id=None)

        if result.success:
            response_text = result.response_text or "Tu cita ha sido cancelada correctamente."
            logger.info("cancel_appointment: appointment %s cancelled successfully", appointment_id)
            return {
                "success": True,
                "appointment_id": appointment_id,
                "within_window": False,
                "hours_until": None,
                "message": response_text,
            }
        else:
            # Propagate within_window flag so the mode can decide on escalation
            logger.warning(
                "cancel_appointment: cancellation failed for %s — within_window=%s",
                appointment_id,
                result.within_window,
            )
            return {
                "success": False,
                "appointment_id": appointment_id,
                "within_window": result.within_window,
                "hours_until": result.hours_until_appointment,
                "message": result.error_message or "No se pudo cancelar la cita.",
            }

    except Exception as exc:
        logger.exception("Error in _cancel_appointment for %s: %s", appointment_id, exc)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "within_window": False,
            "hours_until": None,
            "message": "Ocurrió un error al cancelar la cita. Por favor, intentá de nuevo.",
        }


# ============================================================================
# T4 — reschedule_appointment
# ============================================================================


class RescheduleAppointmentInput(BaseModel):
    """Input schema for reschedule_appointment."""

    appointment_id: str = Field(description="UUID de la cita a reprogramar")
    new_start_time: str = Field(
        description="Nueva fecha y hora en formato ISO 8601 (YYYY-MM-DDTHH:MM:SS)"
    )
    new_stylist_id: str | None = Field(
        default=None,
        description="UUID del nuevo estilista, o None para mantener el actual",
    )


async def _reschedule_appointment(
    appointment_id: str,
    new_start_time: str,
    new_stylist_id: str | None,
    customer_phone: str,  # noqa: ARG001 — available for audit/logging
) -> dict[str, Any]:
    """
    Execute the reschedule of *appointment_id* to *new_start_time*.

    NOTE: `reschedule_service` (T1) is being implemented by a parallel agent.
    The import is attempted at call time; if the module is not yet available
    a TODO response is returned so the mode can surface an informative error.

    IMPORTANT: This tool only executes.  The APPOINTMENT_MANAGEMENT mode's
    `_pre_tool_call` gate ensures the customer has already confirmed the
    reschedule before this function is ever called.
    """
    # Validate appointment UUID
    try:
        appt_uuid = UUID(appointment_id)
    except (ValueError, AttributeError) as exc:
        logger.error("reschedule_appointment: invalid UUID '%s': %s", appointment_id, exc)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "old_start_time": None,
            "new_start_time": new_start_time,
            "within_window": False,
            "slot_taken": False,
            "message": "El ID de la cita no es válido.",
        }

    # Parse new_start_time (ISO 8601), defaulting to Europe/Madrid if no timezone
    try:
        parsed_dt = datetime.fromisoformat(new_start_time)
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=MADRID_TZ)
    except (ValueError, TypeError) as exc:
        logger.error("reschedule_appointment: invalid new_start_time '%s': %s", new_start_time, exc)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "old_start_time": None,
            "new_start_time": new_start_time,
            "within_window": False,
            "slot_taken": False,
            "message": f"El formato de la nueva fecha/hora no es válido: {new_start_time!r}.",
        }

    # Validate optional new_stylist_id
    new_stylist_uuid: UUID | None = None
    if new_stylist_id is not None:
        try:
            new_stylist_uuid = UUID(new_stylist_id)
        except (ValueError, AttributeError) as exc:
            logger.error(
                "reschedule_appointment: invalid new_stylist_id '%s': %s", new_stylist_id, exc
            )
            return {
                "success": False,
                "appointment_id": appointment_id,
                "old_start_time": None,
                "new_start_time": new_start_time,
                "within_window": False,
                "slot_taken": False,
                "message": "El ID del estilista no es válido.",
            }

    try:
        # TODO: reschedule_service (T1) is implemented by a parallel agent.
        # This import will succeed once agent/services/reschedule_service.py exists.
        from agent.services.reschedule_service import execute_reschedule

        result = await execute_reschedule(
            appointment_id=appt_uuid,
            new_start_time=parsed_dt,
            new_stylist_id=new_stylist_uuid,
        )

        if result.success:
            # RescheduleResult (AD-6) does not carry old_start_time; we report
            # the new ISO we sent in — the mode can show it to the user.
            new_iso = parsed_dt.isoformat()
            date_display = _format_date_spanish(parsed_dt)
            time_display = parsed_dt.strftime("%H:%M")
            message = (
                getattr(result, "response_text", None)
                or f"Tu cita ha sido reprogramada para el {date_display} a las {time_display}."
            )
            logger.info(
                "reschedule_appointment: appointment %s rescheduled to %s",
                appointment_id,
                new_iso,
            )
            return {
                "success": True,
                "appointment_id": appointment_id,
                "old_start_time": None,  # not available from RescheduleResult
                "new_start_time": new_iso,
                "within_window": False,
                "slot_taken": False,
                "message": message,
            }
        else:
            logger.warning(
                "reschedule_appointment: reschedule failed for %s — within_window=%s, error=%s",
                appointment_id,
                getattr(result, "within_window", False),
                result.error,
            )
            return {
                "success": False,
                "appointment_id": appointment_id,
                "old_start_time": None,
                "new_start_time": parsed_dt.isoformat(),
                "within_window": getattr(result, "within_window", False),
                "slot_taken": getattr(result, "slot_taken", False),
                "message": result.error or "No se pudo reprogramar la cita.",
            }

    except ImportError:
        # reschedule_service not yet available (parallel T1 agent)
        logger.error("reschedule_appointment: reschedule_service not available yet (T1 pending)")
        return {
            "success": False,
            "appointment_id": appointment_id,
            "old_start_time": None,
            "new_start_time": parsed_dt.isoformat(),
            "within_window": False,
            "slot_taken": False,
            "message": (
                "Lo siento, el servicio de reprogramación no está disponible en este momento. "
                "Por favor, contactá con el equipo para cambiar tu cita."
            ),
        }

    except Exception as exc:
        logger.exception("Error in _reschedule_appointment for %s: %s", appointment_id, exc)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "old_start_time": None,
            "new_start_time": parsed_dt.isoformat(),
            "within_window": False,
            "slot_taken": False,
            "message": "Ocurrió un error al reprogramar la cita. Por favor, intentá de nuevo.",
        }


# ============================================================================
# Tool factory — inject customer_phone via closure (same pattern as BookingMode)
# ============================================================================


def create_appointment_tools(customer_phone: str) -> list[StructuredTool]:
    """
    Create appointment management tools with *customer_phone* injected via closure.

    This follows the same factory pattern used by BookingMode: each inner async
    function closes over `customer_phone` so the LLM never needs to pass it as
    a parameter.

    Args:
        customer_phone: E.164 phone number of the active customer.

    Returns:
        List of three StructuredTool instances ready for the agentic loop.
    """

    async def list_customer_appointments(limit: int = 5) -> dict[str, Any]:
        return await _list_customer_appointments(limit, customer_phone)

    async def cancel_appointment(
        appointment_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return await _cancel_appointment(appointment_id, reason, customer_phone)

    async def reschedule_appointment(
        appointment_id: str,
        new_start_time: str,
        new_stylist_id: str | None = None,
    ) -> dict[str, Any]:
        return await _reschedule_appointment(
            appointment_id, new_start_time, new_stylist_id, customer_phone
        )

    return [
        StructuredTool.from_function(
            name="list_customer_appointments",
            description=(
                "Lista las próximas citas del cliente. "
                "Devuelve una lista estructurada con id, fecha, hora, estilista y estado."
            ),
            args_schema=ListCustomerAppointmentsInput,
            coroutine=list_customer_appointments,
        ),
        StructuredTool.from_function(
            name="cancel_appointment",
            description=(
                "Cancela una cita del cliente. "
                "IMPORTANTE: Solo llamar luego de que el cliente haya confirmado explícitamente. "
                "El modo APPOINTMENT_MANAGEMENT garantiza esto mediante la puerta _pre_tool_call."
            ),
            args_schema=CancelAppointmentInput,
            coroutine=cancel_appointment,
        ),
        StructuredTool.from_function(
            name="reschedule_appointment",
            description=(
                "Reprograma una cita del cliente a una nueva fecha/hora. "
                "IMPORTANTE: Solo llamar luego de que el cliente haya confirmado explícitamente. "
                "El modo APPOINTMENT_MANAGEMENT garantiza esto mediante la puerta _pre_tool_call."
            ),
            args_schema=RescheduleAppointmentInput,
            coroutine=reschedule_appointment,
        ),
    ]
