"""
Booking Tool for v3.0 Architecture.

This module contains only the book() tool which delegates to BookingTransaction.
All helper functions (get_service_by_name, calculate_total, validate_service_combination)
have been removed as they're now handled by:
- service_resolver.py (service name resolution)
- BookingTransaction (validation + atomic booking)
- info_tools.py (service queries)

The book() tool is the single entry point for creating appointments.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Schema
# ============================================================================


class BookSchema(BaseModel):
    """Schema for book tool parameters."""

    customer_id: str = Field(
        description="Customer UUID as string (from manage_customer tool)"
    )
    service_ids: list[str] = Field(
        description="List of Service UUIDs as strings (from resolve_service_names utility)"
    )
    stylist_id: str = Field(
        description="Stylist UUID as string (from check_availability tool)"
    )
    start_time: str = Field(
        description="Appointment start time in ISO 8601 format with timezone (e.g., '2025-11-08T10:00:00+01:00')"
    )


# ============================================================================
# Booking Tool
# ============================================================================


@tool(args_schema=BookSchema)
async def book(
    customer_id: str,
    service_ids: list[str],
    stylist_id: str,
    start_time: str
) -> dict[str, Any]:
    """
    Create a new appointment booking (atomic transaction).

    This is the single entry point for creating appointments in v3.0 architecture.
    Delegates to BookingTransaction which handles:
    - Validation (3-day rule, category consistency, slot availability)
    - Calendar event creation (Google Calendar API)
    - Database persistence (PostgreSQL with SERIALIZABLE isolation)
    - Rollback on any failure (atomic operation)

    Prerequisites (must be completed before calling this tool):
    1. Customer identified/created via manage_customer()
    2. Services resolved from names to UUIDs via resolve_service_names()
    3. Availability checked and slot selected via check_availability()

    Args:
        customer_id: Customer UUID as string
        service_ids: List of Service UUIDs as strings
        stylist_id: Stylist UUID as string
        start_time: Appointment start time (ISO 8601 with timezone)

    Returns:
        Dict with booking result. Structure:

        Success:
            {
                "success": True,
                "appointment_id": str,
                "google_calendar_event_id": str,
                "start_time": str,
                "end_time": str,
                "total_price": float,
                "duration_minutes": int,
                "customer_id": str,
                "stylist_id": str,
                "service_ids": list[str]
            }

        Failure:
            {
                "success": False,
                "error_code": str,  # "CATEGORY_MISMATCH", "SLOT_TAKEN", "DATE_TOO_SOON", etc.
                "error_message": str,
                "details": dict  # Additional error context
            }

    Example:
        >>> # After customer identified, services resolved, availability checked:
        >>> result = await book(
        ...     customer_id="550e8400-e29b-41d4-a716-446655440000",
        ...     service_ids=["...", "..."],
        ...     stylist_id="...",
        ...     start_time="2025-11-08T10:00:00+01:00"
        ... )
        >>> if result["success"]:
        ...     print(f"Booking created: {result['appointment_id']}")
        ... else:
        ...     print(f"Booking failed: {result['error_message']}")

    Notes:
        - Uses SERIALIZABLE transaction isolation to prevent race conditions
        - Creates Google Calendar event before DB commit (rollback on failure)
        - Validates business rules: 3-day rule, category consistency, slot availability
        - All-or-nothing operation: either fully succeeds or fully rolls back
    """
    try:
        # Parse UUIDs
        try:
            customer_uuid = UUID(customer_id)
            service_uuids = [UUID(sid) for sid in service_ids]
            stylist_uuid = UUID(stylist_id)
        except ValueError as e:
            logger.error(f"Invalid UUID format in book() parameters: {e}")
            return {
                "success": False,
                "error_code": "INVALID_UUID",
                "error_message": "ID inválido en los parámetros de reserva",
                "details": {"error": str(e)}
            }

        # Parse start time
        try:
            start_datetime = datetime.fromisoformat(start_time)
        except ValueError as e:
            logger.error(f"Invalid start_time format '{start_time}': {e}")
            return {
                "success": False,
                "error_code": "INVALID_DATETIME",
                "error_message": "Formato de fecha/hora inválido",
                "details": {"error": str(e)}
            }

        logger.info(
            f"Booking requested",
            extra={
                "customer_id": customer_id,
                "service_count": len(service_ids),
                "stylist_id": stylist_id,
                "start_time": start_time
            }
        )

        # Execute BookingTransaction
        from agent.transactions.booking_transaction import BookingTransaction

        result = await BookingTransaction.execute(
            customer_id=customer_uuid,
            service_ids=service_uuids,
            stylist_id=stylist_uuid,
            start_time=start_datetime
        )

        return result

    except Exception as e:
        logger.error(f"Error in book(): {e}", exc_info=True)
        return {
            "success": False,
            "error_code": "BOOKING_ERROR",
            "error_message": "Error al procesar la reserva",
            "details": {"error": str(e)}
        }
