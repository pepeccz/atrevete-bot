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
        description="Customer UUID as string (automatically registered in first interaction)"
    )
    first_name: str = Field(
        description="Customer's first name for this appointment (e.g., 'Pepe')"
    )
    last_name: str | None = Field(
        default=None,
        description="Customer's last name for this appointment (optional, e.g., 'Cabeza Cruz')"
    )
    notes: str | None = Field(
        default=None,
        description="Appointment-specific notes (allergies, preferences, special requests)"
    )
    services: list[str] = Field(
        description="List of service names as strings (e.g., ['Corte de Caballero', 'Barba'])"
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
    first_name: str,
    last_name: str | None,
    notes: str | None,
    services: list[str],
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
    1. Customer automatically registered in first interaction
    2. Availability checked and slot selected via check_availability()
    3. Customer name and notes collected from user

    Args:
        customer_id: Customer UUID as string (from state, auto-registered)
        first_name: Customer's first name for this appointment
        last_name: Customer's last name (optional)
        notes: Appointment-specific notes (allergies, preferences, etc.)
        services: List of service names as strings (e.g., ["Corte de Caballero", "Barba"])
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
                "error_code": str,  # "CATEGORY_MISMATCH", "SLOT_TAKEN", "DATE_TOO_SOON", "AMBIGUOUS_SERVICE", etc.
                "error_message": str,
                "details": dict  # Additional error context
            }

        Ambiguous Service:
            {
                "success": False,
                "error_code": "AMBIGUOUS_SERVICE",
                "error_message": "El servicio '{query}' es ambiguo. Por favor, especifica cuál quieres.",
                "details": {
                    "query": str,
                    "options": [
                        {"id": str, "name": str, "duration_minutes": int, "category": str}
                    ]
                }
            }

    Example:
        >>> # After customer identified and availability checked:
        >>> result = await book(
        ...     customer_id="550e8400-e29b-41d4-a716-446655440000",
        ...     services=["Corte de Caballero", "Barba"],
        ...     stylist_id="...",
        ...     start_time="2025-11-08T10:00:00+01:00"
        ... )
        >>> if result["success"]:
        ...     print(f"Booking created: {result['appointment_id']}")
        ... else:
        ...     print(f"Booking failed: {result['error_message']}")

    Notes:
        - Resolves service names to UUIDs internally using resolve_service_names()
        - Returns ambiguity error if service names match multiple services
        - Uses SERIALIZABLE transaction isolation to prevent race conditions
        - Creates Google Calendar event before DB commit (rollback on failure)
        - Validates business rules: 3-day rule, category consistency, slot availability
        - All-or-nothing operation: either fully succeeds or fully rolls back
    """
    try:
        # Step 1: Resolve service names to UUIDs
        from agent.utils.service_resolver import resolve_service_names

        logger.info(
            f"Resolving service names: {services}",
            extra={"services": services}
        )

        service_uuids, ambiguity_info = await resolve_service_names(services)

        # If ambiguity detected, return error with options for LLM to clarify
        if ambiguity_info:
            logger.warning(
                f"Ambiguous service query in book(): '{ambiguity_info['query']}'",
                extra={"query": ambiguity_info['query'], "options_count": len(ambiguity_info['options'])}
            )
            return {
                "success": False,
                "error_code": "AMBIGUOUS_SERVICE",
                "error_message": f"El servicio '{ambiguity_info['query']}' es ambiguo. Por favor, especifica cuál quieres.",
                "details": ambiguity_info
            }

        # If no services resolved, return error
        if not service_uuids:
            logger.error(f"Could not resolve any service names: {services}")
            return {
                "success": False,
                "error_code": "SERVICES_NOT_FOUND",
                "error_message": f"No se encontraron los servicios solicitados: {', '.join(services)}",
                "details": {"services": services}
            }

        logger.info(
            f"Services resolved: {len(service_uuids)} UUIDs",
            extra={"service_uuids": [str(uuid) for uuid in service_uuids]}
        )

        # Step 2: Parse customer and stylist UUIDs
        try:
            customer_uuid = UUID(customer_id)
            stylist_uuid = UUID(stylist_id)
        except ValueError as e:
            logger.error(f"Invalid UUID format in book() parameters: {e}")
            return {
                "success": False,
                "error_code": "INVALID_UUID",
                "error_message": "ID inválido en los parámetros de reserva",
                "details": {"error": str(e)}
            }

        # Step 3: Parse start time
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
                "first_name": first_name,
                "last_name": last_name,
                "services": services,
                "service_count": len(service_uuids),
                "stylist_id": stylist_id,
                "start_time": start_time
            }
        )

        # Step 4: Execute BookingTransaction
        from agent.transactions.booking_transaction import BookingTransaction

        result = await BookingTransaction.execute(
            customer_id=customer_uuid,
            service_ids=service_uuids,
            stylist_id=stylist_uuid,
            start_time=start_datetime,
            first_name=first_name,
            last_name=last_name,
            notes=notes
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


# ============================================================================
# Helper Function for Service Name Resolution
# ============================================================================


async def get_service_by_name(
    service_name: str,
    fuzzy: bool = True,
    limit: int = 5
) -> list[Any]:
    """
    Get services by name with fuzzy matching using RapidFuzz.

    Used by service_resolver.py to resolve service names to UUIDs.
    Uses the same fuzzy matching algorithm as search_services for consistency.

    Args:
        service_name: Service name to search for
        fuzzy: If True, uses RapidFuzz for fuzzy matching; if False, exact match only
        limit: Maximum number of results to return

    Returns:
        List of Service database models matching the query

    Example:
        >>> services = await get_service_by_name("corte peinado largo", fuzzy=True, limit=5)
        >>> # Returns [Service(name="Corte + Peinado (Largo)"), ...] using RapidFuzz
    """
    from database.connection import get_async_session
    from database.models import Service
    from rapidfuzz import fuzz, process
    from sqlalchemy import select

    async with get_async_session() as session:
        try:
            if fuzzy:
                # Load all active services for fuzzy matching
                query = select(Service).where(Service.is_active == True)
                result = await session.execute(query)
                all_services = list(result.scalars().all())

                if not all_services:
                    logger.warning("No active services found in database")
                    return []

                # Use RapidFuzz for fuzzy matching (same as search_services)
                choices_dict = {s.name: s for s in all_services}
                matches = process.extract(
                    service_name,
                    choices_dict.keys(),
                    scorer=fuzz.WRatio,
                    score_cutoff=45,  # Same threshold as search_services
                    limit=limit
                )

                # Extract matched service objects
                matched_services = [choices_dict[match[0]] for match in matches]

                logger.info(
                    f"Found {len(matched_services)} services matching '{service_name}' using RapidFuzz (fuzzy={fuzzy})"
                )

                return matched_services

            else:
                # Exact match (case-insensitive)
                query = (
                    select(Service)
                    .where(Service.name.ilike(service_name))
                    .where(Service.is_active == True)
                    .limit(limit)
                )

                result = await session.execute(query)
                services = list(result.scalars().all())

                logger.info(
                    f"Found {len(services)} services matching '{service_name}' (exact match)"
                )

                return services

        except Exception as e:
            logger.error(
                f"Error in get_service_by_name('{service_name}', fuzzy={fuzzy}): {e}",
                exc_info=True
            )
            return []  # Return empty list on error, never None


    # Edge case: If async for loop exits without returning (should never happen)
    logger.warning(
        f"get_service_by_name('{service_name}', fuzzy={fuzzy}) "
        f"exited async loop without returning - returning empty list"
    )
    return []
