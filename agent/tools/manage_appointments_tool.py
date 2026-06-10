"""manage_appointments tool — view, cancel, or reschedule appointments.

This tool is available to the booking agent for appointment management actions.

Internal helpers (_list_appointments, _cancel_appointment, _reschedule_appointment)
return structured dicts so they are independently testable. The public @tool
wrapper formats those dicts into the final string returned to the LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.services.availability_service import _load_lead_time_min_days
from agent.tools._booking_validators import (
    validate_appointment_belongs_to_customer,
    validate_booking_date,
)
from database.connection import get_async_session

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers — testable without going through the @tool wrapper
# ─────────────────────────────────────────────────────────────────────────────


async def _list_appointments(customer_phone: str, limit: int = 5) -> dict:
    """
    List upcoming appointments for a customer.

    Returns:
        dict with keys:
            success (bool)
            appointments (list[dict]) — each with id, index, date_display,
                time_display, hours_until, stylist_name, service_names
            count (int)
            message (str) — human-readable summary
    """
    try:
        from agent.services.appointment_query_service import (
            _get_customer_by_phone,
            _get_service_names,
            _get_upcoming_appointments,
            format_date_spanish,
        )

        customer = await _get_customer_by_phone(customer_phone)
        if customer is None:
            return {
                "success": True,
                "appointments": [],
                "count": 0,
                "message": "No tienes citas programadas en este momento.",
            }

        appointments = await _get_upcoming_appointments(customer.id, limit)
        if not appointments:
            return {
                "success": True,
                "appointments": [],
                "count": 0,
                "message": "No tienes citas programadas en este momento.",
            }

        items = []
        now = datetime.now(MADRID_TZ)
        for idx, appt in enumerate(appointments, 1):
            appt_time = appt.start_time.astimezone(MADRID_TZ)
            hours_until = (appt_time - now).total_seconds() / 3600
            service_names = await _get_service_names(appt.service_ids)
            items.append(
                {
                    "index": idx,
                    "id": str(appt.id),
                    "date_display": format_date_spanish(appt_time),
                    "time_display": appt_time.strftime("%H:%M"),
                    "hours_until": round(hours_until, 1),
                    "stylist_name": appt.stylist.name if appt.stylist else "tu estilista",
                    "service_names": service_names,
                }
            )

        return {
            "success": True,
            "appointments": items,
            "count": len(items),
            "message": f"Tienes {len(items)} cita(s) próxima(s).",
        }

    except Exception as exc:
        logger.error("_list_appointments error for %s: %s", customer_phone, exc, exc_info=True)
        return {
            "success": False,
            "appointments": [],
            "count": 0,
            "message": "No pude consultar tus citas en este momento.",
        }


async def _cancel_appointment(
    customer_phone: str,
    appointment_id: str,
    reason: str | None,
    customer_id: UUID | None = None,
) -> dict:
    """
    Cancel a specific appointment by UUID.

    customer_id is the resolved customer UUID from state (CustomerResolveMiddleware).
    When provided, an IDOR guard verifies ownership before any cancellation attempt.

    Returns:
        dict with keys:
            success (bool)
            appointment_id (str)
            message (str)
            error_code (str | None) — APPOINTMENT_ID_REQUIRED | INVALID_UUID |
                CUSTOMER_ID_REQUIRED | APPOINTMENT_NOT_OWNED | WINDOW | SERVICE_ERROR
            within_window (bool)
            hours_until_appointment (int | None)
    """
    if not appointment_id:
        return {
            "success": False,
            "appointment_id": appointment_id or "",
            "message": "Para cancelar necesito el ID de la cita.",
            "error_code": "APPOINTMENT_ID_REQUIRED",
            "within_window": False,
            "hours_until_appointment": None,
        }

    # J2: customer_id must be resolved before any mutation
    if customer_id is None:
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "No pude verificar tu identidad. Por favor, inténtalo de nuevo.",
            "error_code": "CUSTOMER_ID_REQUIRED",
            "within_window": False,
            "hours_until_appointment": None,
        }

    try:
        appt_uuid = UUID(appointment_id)
    except ValueError:
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "El identificador de la cita no es válido.",
            "error_code": "INVALID_UUID",
            "within_window": False,
            "hours_until_appointment": None,
        }

    # J2: IDOR guard — verify ownership before any mutation
    try:
        async with get_async_session() as session:
            idor_result = await validate_appointment_belongs_to_customer(
                session, appt_uuid, customer_id
            )
        if not idor_result.ok:
            logger.warning(
                "manage_appointments.idor_rejected",
                extra={
                    "action": "cancel",
                    "appointment_id": str(appt_uuid),
                    "customer_id": str(customer_id),
                    "error_code": idor_result.error_code,
                },
            )
            return {
                "success": False,
                "appointment_id": appointment_id,
                "message": idor_result.error_message
                or "No encontré esa cita asociada a tu cuenta.",
                "error_code": idor_result.error_code,
                "within_window": False,
                "hours_until_appointment": None,
            }
    except Exception as exc:
        logger.error("_cancel_appointment idor check failed: %s", exc, exc_info=True)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "Hubo un problema al verificar la cita.",
            "error_code": "SERVICE_ERROR",
            "within_window": False,
            "hours_until_appointment": None,
        }

    try:
        from agent.services.cancellation_service import execute_cancellation

        result = await execute_cancellation(
            appointment_id=appt_uuid,
            customer_phone=customer_phone,
            reason=reason,
            conversation_id=None,
        )

        if result.success:
            return {
                "success": True,
                "appointment_id": appointment_id,
                "message": result.response_text or "Tu cita ha sido cancelada.",
                "error_code": None,
                "within_window": False,
                "hours_until_appointment": None,
            }

        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": result.error_message or "No pude cancelar la cita.",
            "error_code": "WINDOW" if result.within_window else "SERVICE_ERROR",
            "within_window": result.within_window,
            "hours_until_appointment": result.hours_until_appointment,
        }

    except Exception as exc:
        logger.error("_cancel_appointment error for %s: %s", appointment_id, exc, exc_info=True)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "Hubo un problema al cancelar la cita.",
            "error_code": "SERVICE_ERROR",
            "within_window": False,
            "hours_until_appointment": None,
        }


async def _reschedule_appointment(
    customer_phone: str,
    appointment_id: str,
    new_date: str,
    new_time: str,
    reason: str | None,
    customer_id: UUID | None = None,
) -> dict:
    """
    Reschedule a specific appointment.

    customer_id is the resolved customer UUID from state (CustomerResolveMiddleware).
    When provided, an IDOR guard verifies ownership before any reschedule attempt.

    Returns:
        dict with keys:
            success (bool)
            appointment_id (str)
            message (str)
            error_code (str | None) — APPOINTMENT_ID_REQUIRED | RESCHEDULE_PARAMS_REQUIRED |
                INVALID_UUID | CUSTOMER_ID_REQUIRED | APPOINTMENT_NOT_OWNED |
                BAD_DATE_FORMAT | INELIGIBLE | SLOT_TAKEN | SERVICE_ERROR
            new_start_time (str | None) — ISO format when success=True
    """
    if not appointment_id:
        return {
            "success": False,
            "appointment_id": appointment_id or "",
            "message": "Para reprogramar necesito el ID de la cita.",
            "error_code": "APPOINTMENT_ID_REQUIRED",
            "new_start_time": None,
        }

    if not new_date or not new_time:
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "Para reprogramar necesito la nueva fecha y hora.",
            "error_code": "RESCHEDULE_PARAMS_REQUIRED",
            "new_start_time": None,
        }

    # J2: customer_id must be resolved before any mutation
    if customer_id is None:
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "No pude verificar tu identidad. Por favor, inténtalo de nuevo.",
            "error_code": "CUSTOMER_ID_REQUIRED",
            "new_start_time": None,
        }

    try:
        appt_uuid = UUID(appointment_id)
    except ValueError:
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "El identificador de la cita no es válido.",
            "error_code": "INVALID_UUID",
            "new_start_time": None,
        }

    # J2: IDOR guard — verify ownership before any mutation
    try:
        async with get_async_session() as session:
            idor_result = await validate_appointment_belongs_to_customer(
                session, appt_uuid, customer_id
            )
        if not idor_result.ok:
            logger.warning(
                "manage_appointments.idor_rejected",
                extra={
                    "action": "reschedule",
                    "appointment_id": str(appt_uuid),
                    "customer_id": str(customer_id),
                    "error_code": idor_result.error_code,
                },
            )
            return {
                "success": False,
                "appointment_id": appointment_id,
                "message": idor_result.error_message
                or "No encontré esa cita asociada a tu cuenta.",
                "error_code": idor_result.error_code,
                "new_start_time": None,
            }
    except Exception as exc:
        logger.error("_reschedule_appointment idor check failed: %s", exc, exc_info=True)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "Hubo un problema al verificar la cita.",
            "error_code": "SERVICE_ERROR",
            "new_start_time": None,
        }

    try:
        from agent.services.reschedule_service import (
            execute_reschedule,
            validate_reschedule_eligibility,
        )

        # Step 1 — eligibility (ownership + status + 48h window)
        eligibility = await validate_reschedule_eligibility(
            appointment_id=appt_uuid,
            customer_phone=customer_phone,
        )
        if not eligibility.eligible:
            return {
                "success": False,
                "appointment_id": appointment_id,
                "message": eligibility.reason,
                "error_code": "INELIGIBLE",
                "new_start_time": None,
            }

        # Step 1b — booking-date validation (G1 → G2 → G3)
        # Called before datetime.strptime so guard errors are caught early without DB writes.
        _min_days = await _load_lead_time_min_days()
        date_validation = await validate_booking_date(
            date_iso=new_date, date_text=new_date, min_days=_min_days
        )
        if not date_validation.ok:
            return {
                "success": False,
                "error_code": date_validation.error_code,
                "message": date_validation.error_message,
                **date_validation.payload,
            }

        # Step 2 — parse datetime with Madrid timezone
        try:
            naive = datetime.strptime(f"{date_validation.date_iso} {new_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return {
                "success": False,
                "appointment_id": appointment_id,
                "message": (
                    "La fecha u hora no tienen el formato correcto " "(YYYY-MM-DD y HH:MM)."
                ),
                "error_code": "BAD_DATE_FORMAT",
                "new_start_time": None,
            }
        new_start = naive.replace(tzinfo=MADRID_TZ)

        # Step 3 — execute reschedule
        result = await execute_reschedule(
            appointment_id=appt_uuid,
            new_start_time=new_start,
        )

        if result.success:
            new_start_display = result.new_start_time.astimezone(MADRID_TZ).strftime(
                "%Y-%m-%d a las %H:%M"
            )
            return {
                "success": True,
                "appointment_id": appointment_id,
                "message": f"Tu cita ha sido reprogramada para el {new_start_display}.",
                "error_code": None,
                "new_start_time": (
                    result.new_start_time.isoformat() if result.new_start_time else None
                ),
            }

        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": result.error or "No pude reprogramar la cita.",
            "error_code": "SLOT_TAKEN" if result.slot_taken else "SERVICE_ERROR",
            "new_start_time": None,
        }

    except Exception as exc:
        logger.error("_reschedule_appointment error for %s: %s", appointment_id, exc, exc_info=True)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "Hubo un problema al reprogramar la cita.",
            "error_code": "SERVICE_ERROR",
            "new_start_time": None,
        }


async def _confirm_or_decline(
    customer_phone: str,
    appointment_id: str,
    *,
    confirm: bool,
) -> dict:
    """Shared helper for tool-driven confirm/decline actions."""
    error_label = "confirmar" if confirm else "rechazar"
    if not appointment_id:
        return {
            "success": False,
            "appointment_id": appointment_id or "",
            "message": f"Para {error_label} necesito el ID de la cita.",
            "error_code": "APPOINTMENT_ID_REQUIRED",
        }
    try:
        appt_uuid = UUID(appointment_id)
    except ValueError:
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": "El identificador de la cita no es válido.",
            "error_code": "INVALID_UUID",
        }

    try:
        from agent.routing.intent_types import IntentType
        from agent.services.confirmation_service import handle_tool_action

        decision = IntentType.CONFIRM_APPOINTMENT if confirm else IntentType.DECLINE_APPOINTMENT
        result = await handle_tool_action(appt_uuid, decision)

        error_code: str | None = None
        if not result.success and result.state_updates:
            error_code = result.state_updates.get("error_code")

        message = (
            result.response_text
            or result.error_message
            or ("Cita confirmada." if confirm else "Cita cancelada.")
        )
        return {
            "success": result.success,
            "appointment_id": appointment_id,
            "message": message,
            "error_code": error_code,
        }
    except Exception as exc:
        logger.error("_confirm_or_decline error for %s: %s", appointment_id, exc, exc_info=True)
        return {
            "success": False,
            "appointment_id": appointment_id,
            "message": f"Hubo un problema al {error_label} la cita.",
            "error_code": "SERVICE_ERROR",
        }


async def _confirm_appointment(customer_phone: str, appointment_id: str) -> dict:
    return await _confirm_or_decline(customer_phone, appointment_id, confirm=True)


async def _decline_appointment(customer_phone: str, appointment_id: str) -> dict:
    return await _confirm_or_decline(customer_phone, appointment_id, confirm=False)


# ─────────────────────────────────────────────────────────────────────────────
# Public @tool wrapper
# ─────────────────────────────────────────────────────────────────────────────


@tool
async def manage_appointments(
    action: Literal["list", "cancel", "reschedule", "confirm", "decline"],
    appointment_id: str | None = None,
    new_date: str | None = None,
    new_time: str | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """Manage customer appointments: list, cancel, reschedule, confirm or decline.

    customer_phone is injected from session state; it is not a tool argument.

    Args:
        action: Action to perform — list (view upcoming), cancel, reschedule,
            confirm (accept a pending confirmation), or decline (reject one).
        appointment_id: Appointment UUID — required for cancel, reschedule, confirm, decline.
        new_date: New date (YYYY-MM-DD) — required for reschedule action.
        new_time: New time slot (HH:MM) — required for reschedule action.

    Reprogramar solo cambia fecha y hora. El cambio de estilista no está
    disponible por chat; si el cliente lo pide, escala a un humano.
    """
    _state = state or {}
    customer_phone = _state.get("customer_phone") or ""
    if not customer_phone:
        logger.error(
            "manage_appointments.state.missing_customer_phone",
            extra={"tool_name": "manage_appointments"},
        )
        return "Estado de conversación incompleto. No puedo gestionar la cita."

    # J2: extract customer_id from state (set by CustomerResolveMiddleware)
    _customer_id_raw = _state.get("customer_id")
    _customer_id: UUID | None = None
    if _customer_id_raw is not None:
        try:
            _customer_id = UUID(str(_customer_id_raw))
        except (ValueError, AttributeError):
            pass

    try:
        if action == "list":
            result = await _list_appointments(customer_phone=customer_phone)
            if not result["success"]:
                return result["message"]
            if result["count"] == 0:
                return result["message"]
            # Format the structured list as a readable string for the LLM
            lines = []
            for item in result["appointments"]:
                lines.append(
                    f"- {item['date_display']} a las {item['time_display']} "
                    f"con {item['stylist_name']} ({item['service_names']}) "
                    f"[ID: {item['id']}]"
                )
            return result["message"] + "\n" + "\n".join(lines)

        if action == "cancel":
            result = await _cancel_appointment(
                customer_phone=customer_phone,
                appointment_id=appointment_id or "",
                reason=None,
                customer_id=_customer_id,
            )
            return result["message"]

        if action == "confirm":
            result = await _confirm_appointment(
                customer_phone=customer_phone,
                appointment_id=appointment_id or "",
            )
            return result["message"]

        if action == "decline":
            result = await _decline_appointment(
                customer_phone=customer_phone,
                appointment_id=appointment_id or "",
            )
            return result["message"]

        if action == "reschedule":
            result = await _reschedule_appointment(
                customer_phone=customer_phone,
                appointment_id=appointment_id or "",
                new_date=new_date or "",
                new_time=new_time or "",
                reason=None,
                customer_id=_customer_id,
            )
            return result["message"]

        return "Acción no reconocida."

    except Exception as exc:
        logger.error("manage_appointments error: %s", exc, exc_info=True)
        return "Hubo un problema al gestionar tu cita. Por favor, inténtalo de nuevo."
