"""manage_appointments tool — view, cancel, or reschedule appointments.

This tool is available to the booking agent for appointment management actions.
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ManageAppointmentsSchema(BaseModel):
    """Input schema for manage_appointments tool."""

    action: Literal["list", "cancel", "reschedule"] = Field(
        description="Action to perform: list (view upcoming), cancel, or reschedule."
    )
    customer_phone: str = Field(description="Customer phone number (E.164 format).")
    appointment_id: str | None = Field(
        default=None,
        description="Appointment UUID — required for cancel and reschedule actions.",
    )
    new_date: str | None = Field(
        default=None,
        description="New date (YYYY-MM-DD) — required for reschedule action.",
    )
    new_time: str | None = Field(
        default=None,
        description="New time slot (HH:MM) — required for reschedule action.",
    )


@tool(args_schema=ManageAppointmentsSchema)
async def manage_appointments(
    action: Literal["list", "cancel", "reschedule"],
    customer_phone: str,
    appointment_id: str | None = None,
    new_date: str | None = None,
    new_time: str | None = None,
) -> str:
    """Manage customer appointments: list upcoming, cancel, or reschedule.

    Use 'list' to show upcoming appointments, 'cancel' to cancel one (requires
    appointment_id), or 'reschedule' to change date/time (requires appointment_id,
    new_date, new_time).
    """
    try:
        if action == "list":
            from agent.services.appointment_query_service import get_upcoming_appointments

            appointments = await get_upcoming_appointments(customer_phone=customer_phone)
            if not appointments:
                return "No tienes citas próximas registradas."
            lines = ["Tus citas próximas:"]
            for appt in appointments:
                lines.append(
                    f"- {appt.date_es} {appt.time_es} — "
                    f"{appt.service_name} con {appt.stylist_name} "
                    f"(ID: {appt.appointment_id})"
                )
            return "\n".join(lines)

        if action == "cancel":
            if not appointment_id:
                return "Para cancelar necesito el ID de la cita."
            from agent.services.cancellation_service import execute_cancellation

            result = await execute_cancellation(
                appointment_id=appointment_id,
                customer_phone=customer_phone,
            )
            if result.success:
                return "Tu cita ha sido cancelada correctamente."
            return f"No pude cancelar la cita: {result.error_message or 'error desconocido'}"

        if action == "reschedule":
            if not appointment_id:
                return "Para reprogramar necesito el ID de la cita."
            if not new_date or not new_time:
                return "Para reprogramar necesito la nueva fecha y hora."
            from agent.services.reschedule_service import reschedule_appointment

            result = await reschedule_appointment(
                appointment_id=appointment_id,
                customer_phone=customer_phone,
                new_date=new_date,
                new_time=new_time,
            )
            if result.get("success"):
                return f"Tu cita ha sido reprogramada para el {new_date} a las {new_time}."
            return f"No pude reprogramar la cita: {result.get('error', 'error desconocido')}"

        return "Acción no reconocida."

    except Exception as exc:
        logger.error("manage_appointments error: %s", exc, exc_info=True)
        return "Hubo un problema al gestionar tu cita. Por favor, inténtalo de nuevo."
