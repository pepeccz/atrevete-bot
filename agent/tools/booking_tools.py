"""
Booking Tool for v4.0 Architecture (DB-First, simplified).

Redesigned for T-06:
- customer get-or-create by phone (no pre-registered customer_id required)
- services validated by exact name match via _resolve_service_by_name
- slot_index resolved to stylist_id + start_time by booking_mode._pre_tool_call hook
- RapidFuzz / service_resolver / sentinel values all removed
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.connection import get_async_session
from database.models import Customer

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Schema
# ============================================================================


class BookSchema(BaseModel):
    """Schema for book tool parameters.

    NOTE: stylist_id and start_time are NOT declared here — they are injected
    at runtime by booking_mode._pre_tool_call after resolving slot_index.
    """

    customer_phone: str = Field(description="Teléfono del cliente en formato E.164")
    customer_first_name: str = Field(description="Nombre del cliente")
    customer_last_name: str | None = Field(
        default=None, description="Apellido del cliente (opcional)"
    )
    services: list[str] = Field(description="Lista de nombres exactos de servicios del catálogo")
    slot_index: int = Field(
        description="Índice del slot elegido (1-based) del resultado de check_availability"
    )
    notes: str | None = Field(default=None, description="Notas de la cita (alergias, preferencias)")
    conversation_id: str | None = Field(
        default=None, description="ID de conversación de Chatwoot"
    )


# ============================================================================
# Customer Helper
# ============================================================================


async def _get_or_create_customer(
    phone: str, first_name: str, last_name: str | None = None
) -> Customer | None:
    """
    Normalize phone, lookup by phone, create if not found, update name if changed.

    Returns Customer object on success, None on failure.
    """
    from agent.tools.customer_tools import normalize_phone

    normalized = normalize_phone(phone)
    if not normalized:
        logger.warning(f"_get_or_create_customer: invalid phone '{phone}'")
        return None

    async with get_async_session() as session:
        try:
            result = await session.execute(
                select(Customer).where(Customer.phone == normalized)
            )
            customer = result.scalar_one_or_none()

            if customer is None:
                customer = Customer(
                    id=uuid4(),
                    phone=normalized,
                    first_name=first_name,
                    last_name=last_name,
                )
                session.add(customer)
                await session.commit()
                await session.refresh(customer)
                logger.info(
                    "Customer created",
                    extra={"customer_id": str(customer.id), "phone": normalized},
                )
            else:
                # Update name if it changed
                name_changed = (
                    customer.first_name != first_name
                    or customer.last_name != last_name
                )
                if name_changed:
                    customer.first_name = first_name
                    customer.last_name = last_name
                    await session.commit()
                    await session.refresh(customer)
                    logger.info(
                        "Customer name updated",
                        extra={"customer_id": str(customer.id)},
                    )
                else:
                    logger.info(
                        "Customer found (no changes)",
                        extra={"customer_id": str(customer.id)},
                    )

            return customer

        except IntegrityError as e:
            await session.rollback()
            # Race condition: another request created the customer concurrently
            logger.warning(
                f"_get_or_create_customer IntegrityError (concurrent create), retrying lookup: {e}"
            )
            result = await session.execute(
                select(Customer).where(Customer.phone == normalized)
            )
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"_get_or_create_customer error: {e}", exc_info=True)
            return None


# ============================================================================
# Booking Tool
# ============================================================================


@tool(args_schema=BookSchema)
async def book(
    customer_phone: str,
    customer_first_name: str,
    customer_last_name: str | None = None,
    services: list[str] | None = None,
    slot_index: int = 0,
    notes: str | None = None,
    conversation_id: str | None = None,
    # Injected at runtime by booking_mode._pre_tool_call (not in schema):
    stylist_id: str | None = None,
    start_time: str | None = None,
) -> dict[str, Any]:
    """
    Create a new appointment booking (atomic transaction).

    Prerequisite: customer must have confirmed the booking summary.
    The slot must have been selected via check_availability() first.

    Resolves or creates the customer by phone, validates services against
    the catalog by exact name, then delegates to BookingTransaction for
    the atomic DB write + GCal push.

    Args:
        customer_phone: Customer phone in E.164 format
        customer_first_name: Customer first name
        customer_last_name: Customer last name (optional)
        services: List of exact service names from the catalog
        slot_index: 1-based index of the chosen slot from check_availability
        notes: Appointment notes (allergies, preferences, etc.)
        conversation_id: Chatwoot conversation ID
        stylist_id: Injected by _pre_tool_call from resolved slot (not in schema)
        start_time: Injected by _pre_tool_call from resolved slot (not in schema)

    Returns:
        Success:
            {
                "success": True,
                "appointment_id": str,
                "customer_id": str,
                "customer_name": str,
                "stylist_name": str,
                "start_time": str,
                "end_time": str,
                "duration_minutes": int,
                "services": [{"name": str, "duration_minutes": int}],
                "google_calendar_event_id": str | None,
                "error_code": None,
                "error_message": None,
                "_internal_flags": {"appointment_created": True}
            }

        Failure:
            {
                "success": False,
                "error_code": str,
                "error_message": str
            }

    Error codes: SERVICE_NOT_FOUND, SLOT_TAKEN, INVALID_PHONE,
                 DURATION_MISMATCH, CUSTOMER_CREATE_FAILED, EMPTY_SERVICES
    """
    try:
        # ── 1. Validate services list ──────────────────────────────────────────
        if not services:
            logger.error("book(): services list is empty")
            return {
                "success": False,
                "error_code": "EMPTY_SERVICES",
                "error_message": "Debés indicar al menos un servicio.",
                "error_details": {},
            }

        # ── 2. Get-or-create customer ──────────────────────────────────────────
        customer = await _get_or_create_customer(
            phone=customer_phone,
            first_name=customer_first_name,
            last_name=customer_last_name,
        )
        if customer is None:
            normalized_ok = True
            from agent.tools.customer_tools import normalize_phone
            if not normalize_phone(customer_phone):
                normalized_ok = False

            if not normalized_ok:
                logger.error(f"book(): invalid phone '{customer_phone}'")
                return {
                    "success": False,
                    "error_code": "INVALID_PHONE",
                    "error_message": (
                        f"El teléfono '{customer_phone}' no es válido. "
                        "Usá formato E.164 (ej: +34612345678)."
                    ),
                    "error_details": {"phone": customer_phone},
                }

            logger.error(f"book(): could not create/find customer for phone '{customer_phone}'")
            return {
                "success": False,
                "error_code": "CUSTOMER_CREATE_FAILED",
                "error_message": "No se pudo registrar al cliente. Intentá de nuevo.",
                "error_details": {"phone": customer_phone},
            }

        # ── 3. Resolve services by exact name ──────────────────────────────────
        from agent.tools.availability_tools import _resolve_service_by_name

        resolved_services = []
        for service_name in services:
            svc = await _resolve_service_by_name(service_name)
            if svc is None:
                logger.warning(f"book(): service not found: '{service_name}'")
                return {
                    "success": False,
                    "error_code": "SERVICE_NOT_FOUND",
                    "error_message": (
                        f"El servicio '{service_name}' no está en el catálogo. "
                        "Verificá que el nombre sea exacto."
                    ),
                    "error_details": {"service_name": service_name},
                }
            resolved_services.append(svc)

        service_ids = [svc.id for svc in resolved_services]
        total_duration = sum(svc.duration_minutes for svc in resolved_services)

        logger.info(
            "Services resolved for booking",
            extra={
                "services": [svc.name for svc in resolved_services],
                "total_duration": total_duration,
            },
        )

        # ── 4. Validate injected slot data (from _pre_tool_call) ───────────────
        if not stylist_id or not start_time:
            logger.error(
                "book(): stylist_id or start_time not injected by _pre_tool_call",
                extra={"stylist_id": stylist_id, "start_time": start_time},
            )
            return {
                "success": False,
                "error_code": "SLOT_NOT_RESOLVED",
                "error_message": (
                    "No se pudo determinar el horario. "
                    "Seleccioná un slot con check_availability primero."
                ),
                "error_details": {},
            }

        try:
            stylist_uuid = UUID(stylist_id)
        except (ValueError, TypeError) as e:
            logger.error(f"book(): invalid stylist_id UUID '{stylist_id}': {e}")
            return {
                "success": False,
                "error_code": "SLOT_NOT_RESOLVED",
                "error_message": "ID de estilista inválido.",
                "error_details": {"stylist_id": stylist_id},
            }

        try:
            start_datetime = datetime.fromisoformat(start_time)
        except (ValueError, TypeError) as e:
            logger.error(f"book(): invalid start_time '{start_time}': {e}")
            return {
                "success": False,
                "error_code": "SLOT_NOT_RESOLVED",
                "error_message": "Formato de fecha/hora inválido en el slot seleccionado.",
                "error_details": {"start_time": start_time},
            }

        logger.info(
            "Booking requested",
            extra={
                "customer_id": str(customer.id),
                "customer_phone": customer_phone,
                "customer_name": customer_first_name,
                "services": [svc.name for svc in resolved_services],
                "service_count": len(service_ids),
                "stylist_id": stylist_id,
                "start_time": start_time,
                "total_duration": total_duration,
            },
        )

        # ── 5. Execute BookingTransaction ──────────────────────────────────────
        from agent.transactions.booking_transaction import BookingTransaction

        result = await BookingTransaction.execute(
            customer_id=customer.id,
            service_ids=service_ids,
            stylist_id=stylist_uuid,
            start_time=start_datetime,
            first_name=customer_first_name,
            last_name=customer_last_name,
            notes=notes,
            conversation_id=conversation_id,
        )

        # ── 6. Enrich success response with new schema fields ──────────────────
        if result.get("success"):
            services_detail = [
                {"name": svc.name, "duration_minutes": svc.duration_minutes}
                for svc in resolved_services
            ]
            result["services"] = services_detail
            result["error_code"] = None
            result["error_message"] = None
            result["_internal_flags"] = {"appointment_created": True}

        return result

    except Exception as e:
        logger.error(f"Error in book(): {e}", exc_info=True)
        return {
            "success": False,
            "error_code": "BOOKING_ERROR",
            "error_message": "Error al procesar la reserva",
            "error_details": {"error": str(e)},
        }
