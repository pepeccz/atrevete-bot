"""
Hold tools: create_hold and confirm_from_hold.

These tools implement the HOLD pattern to close the race condition window
between availability check and booking confirmation.

Architecture (L2 defense):
- create_hold(): INSERT with status=HOLD and hold_expires_at=NOW()+5min.
  The DB-level GIST exclusion constraint (excl_no_overlap) fires atomically
  if the slot is already occupied — IntegrityError is mapped to SLOT_UNAVAILABLE.
- confirm_from_hold(): SERIALIZABLE transaction with SELECT FOR UPDATE, checks
  expiry, promotes HOLD → PENDING, clears hold_expires_at.

Error codes returned (never raised):
    SLOT_UNAVAILABLE  — slot is already occupied by another appointment
    HOLD_EXPIRED      — hold_expires_at <= NOW() at confirm time
    HOLD_INVALID_STATE — appointment is not in HOLD status (e.g. already confirmed)
    HOLD_NOT_FOUND    — no appointment found for the given hold_id
    INVALID_START_TIME — start_time string is not valid ISO 8601
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text as sa_text

from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus

logger = logging.getLogger(__name__)

# ── Error code constants ─────────────────────────────────────────────────────

SLOT_UNAVAILABLE = "SLOT_UNAVAILABLE"
HOLD_EXPIRED = "HOLD_EXPIRED"
HOLD_INVALID_STATE = "HOLD_INVALID_STATE"
HOLD_NOT_FOUND = "HOLD_NOT_FOUND"

# Time-to-live for a HOLD slot before it expires
HOLD_TTL_MINUTES = 5


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class CreateHoldSchema(BaseModel):
    """Input schema for create_hold tool."""

    stylist_id: str = Field(..., description="UUID of the stylist")
    service_ids: list[str] = Field(..., description="List of service UUIDs")
    start_time: str = Field(..., description="ISO 8601 start datetime with timezone")
    customer_id: str = Field(..., description="UUID of the customer")
    duration_minutes: int = Field(..., description="Duration of the appointment in minutes")
    idempotency_key: str = Field(
        ..., description="Unique key to prevent duplicate holds (use conversation_id + slot hash)"
    )
    first_name: str = Field(..., description="Customer first name for the appointment record")


class ConfirmFromHoldSchema(BaseModel):
    """Input schema for confirm_from_hold tool."""

    hold_id: str = Field(..., description="UUID of the HOLD appointment to confirm")


# ── Tools ────────────────────────────────────────────────────────────────────


@tool(args_schema=CreateHoldSchema)
async def create_hold(
    stylist_id: str,
    service_ids: list[str],
    start_time: str,
    customer_id: str,
    duration_minutes: int,
    idempotency_key: str,
    first_name: str,
) -> dict[str, Any]:
    """
    Creates a temporary HOLD on a time slot for a stylist.

    The hold expires in 5 minutes if not confirmed via confirm_from_hold().
    The DB-level GIST exclusion constraint fires atomically if the slot is occupied
    (concurrent requests), returning SLOT_UNAVAILABLE without raising.

    Returns:
        Success: {"status": "ok", "hold_id": "<uuid>", "expires_at": "<iso>"}
        Error:   {"status": "error", "error": "<CODE>", "message": "<str>"}
    """
    try:
        start_dt = datetime.fromisoformat(start_time)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
    except ValueError as e:
        return {
            "status": "error",
            "error": "INVALID_START_TIME",
            "message": str(e),
        }

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=HOLD_TTL_MINUTES)

    async with get_async_session() as session:
        try:
            hold = Appointment(
                id=uuid.uuid4(),
                stylist_id=UUID(stylist_id),
                customer_id=UUID(customer_id),
                service_ids=[UUID(s) for s in service_ids],
                start_time=start_dt,
                duration_minutes=duration_minutes,
                status=AppointmentStatus.HOLD,
                hold_expires_at=expires_at,
                first_name=first_name,
            )
            session.add(hold)
            await session.commit()
            await session.refresh(hold)

            logger.info(
                "HOLD created",
                extra={
                    "hold_id": str(hold.id),
                    "stylist_id": stylist_id,
                    "start_time": start_time,
                    "expires_at": expires_at.isoformat(),
                    "idempotency_key": idempotency_key,
                },
            )

            return {
                "status": "ok",
                "hold_id": str(hold.id),
                "expires_at": expires_at.isoformat(),
            }

        except IntegrityError as e:
            await session.rollback()
            error_msg = str(e)
            if "excl_no_overlap" in error_msg:
                logger.warning(
                    "HOLD failed: slot occupied (excl_no_overlap fired)",
                    extra={
                        "stylist_id": stylist_id,
                        "start_time": start_time,
                        "idempotency_key": idempotency_key,
                    },
                )
                return {
                    "status": "error",
                    "error": SLOT_UNAVAILABLE,
                    "message": "El horario seleccionado ya no está disponible.",
                }
            # Re-raise unexpected integrity errors (FK violations, NOT NULL, etc.)
            raise


@tool(args_schema=ConfirmFromHoldSchema)
async def confirm_from_hold(hold_id: str) -> dict[str, Any]:
    """
    Promotes a HOLD appointment to PENDING (confirmed booking).

    Must be called after the user explicitly confirms the booking details.
    Runs inside a SERIALIZABLE transaction with SELECT FOR UPDATE for atomicity.

    Returns:
        Success: {"status": "ok", "appointment_id": str, "start_time": str, "duration_minutes": int}
        Error:   {"status": "error", "error": "<CODE>", "message": "<str>"}
    """
    async with get_async_session() as session:
        try:
            await session.execute(sa_text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

            # Lock the row to prevent concurrent confirmation attempts
            result = await session.execute(
                select(Appointment).where(Appointment.id == UUID(hold_id)).with_for_update()
            )
            hold = result.scalar_one_or_none()

            if hold is None:
                return {
                    "status": "error",
                    "error": HOLD_NOT_FOUND,
                    "message": "No se encontró la reserva temporal.",
                }

            if hold.status != AppointmentStatus.HOLD:
                logger.warning(
                    "confirm_from_hold: appointment not in HOLD status",
                    extra={"hold_id": hold_id, "actual_status": hold.status.value},
                )
                return {
                    "status": "error",
                    "error": HOLD_INVALID_STATE,
                    "message": "La reserva temporal ya fue procesada.",
                }

            now = datetime.now(timezone.utc)
            if hold.hold_expires_at and hold.hold_expires_at <= now:
                logger.warning(
                    "confirm_from_hold: HOLD expired",
                    extra={
                        "hold_id": hold_id,
                        "hold_expires_at": hold.hold_expires_at.isoformat(),
                        "now": now.isoformat(),
                    },
                )
                return {
                    "status": "error",
                    "error": HOLD_EXPIRED,
                    "message": (
                        "El horario reservado ya no está disponible, te muestro otras opciones."
                    ),
                }

            # Promote HOLD → PENDING
            hold.status = AppointmentStatus.PENDING
            hold.hold_expires_at = None
            await session.commit()
            await session.refresh(hold)

            logger.info(
                "HOLD confirmed → PENDING",
                extra={
                    "appointment_id": str(hold.id),
                    "stylist_id": str(hold.stylist_id),
                    "start_time": hold.start_time.isoformat(),
                },
            )

            return {
                "status": "ok",
                "appointment_id": str(hold.id),
                "start_time": hold.start_time.isoformat(),
                "duration_minutes": hold.duration_minutes,
            }

        except Exception:
            await session.rollback()
            raise
