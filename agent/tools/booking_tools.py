"""
Booking tools for service and pack query functions.

Provides functions to:
- Search services by name with fuzzy matching
- Query packs containing specific services
- Calculate totals for multiple services
- Validate service combinations by category
"""

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import Service, ServiceCategory

logger = logging.getLogger(__name__)


# ============================================================================
# Tool Schemas for LangChain
# ============================================================================


class GetServicesSchema(BaseModel):
    """Schema for get_services tool parameters."""

    category: str | None = Field(
        default=None,
        description="Optional service category filter: 'Hairdressing' or 'Aesthetics'"
    )


async def get_service_by_name(name: str, fuzzy: bool = True, limit: int = 5) -> list[Service]:
    """
    Search for services by name (can return multiple matches for ambiguous queries).

    Args:
        name: Service name to search for
        fuzzy: If True, use pg_trgm similarity matching (threshold > 0.3).
               If False, use exact case-insensitive ILIKE matching.
        limit: Maximum number of results to return (default: 5)

    Returns:
        List of Service objects ordered by relevance (similarity DESC).
        Empty list if no matches found.

    Example:
        >>> services = await get_service_by_name("mechas")  # May return multiple "Mechas" services
        >>> services = await get_service_by_name("corte", fuzzy=True)  # Returns all "corte" variations
        >>> if len(services) == 1:
        ...     # Unambiguous - use directly
        ...     service = services[0]
        >>> elif len(services) > 1:
        ...     # Ambiguous - ask user to clarify
        ...     present_options_to_user(services)
    """
    try:
        logger.info(f"Searching service: name='{name}', fuzzy={fuzzy}, limit={limit}")

        async for session in get_async_session():
            if fuzzy:
                # Use pg_trgm similarity with threshold > 0.3
                stmt = (
                    select(Service)
                    .where(
                        func.similarity(Service.name, name) > 0.3,
                        Service.is_active == True,
                    )
                    .order_by(func.similarity(Service.name, name).desc())
                    .limit(limit)
                )
            else:
                # Use exact case-insensitive match
                stmt = (
                    select(Service)
                    .where(
                        Service.name.ilike(f"%{name}%"),
                        Service.is_active == True,
                    )
                    .limit(limit)
                )

            result = await session.execute(stmt)
            services = list(result.scalars().all())

            if services:
                logger.info(
                    f"Found {len(services)} service(s) for query '{name}': "
                    f"{[s.name for s in services]}"
                )
            else:
                logger.debug(f"No services found for query '{name}'")

            return services

    except Exception as e:
        logger.exception(f"Error searching service '{name}': {e}")
        return []


async def calculate_total(service_ids: list[UUID]) -> dict:
    """
    Calculate total price and duration for a list of services.

    Args:
        service_ids: List of service UUIDs to calculate totals for

    Returns:
        Dictionary with:
        - total_price: Sum of service prices (Decimal)
        - total_duration: Sum of service durations in minutes (int)
        - service_count: Number of services (int)
        - services: List of Service objects for reference

    Example:
        >>> total = await calculate_total([mechas_id, corte_id])
        >>> # Returns {"total_price": Decimal("85.00"), "total_duration": 180, ...}
    """
    try:
        logger.info(f"Calculating total for {len(service_ids)} services")

        if not service_ids:
            logger.debug("Empty service_ids list, returning zero totals")
            return {
                "total_price": Decimal("0.00"),
                "total_duration": 0,
                "service_count": 0,
                "services": [],
            }

        async for session in get_async_session():
            # Query services by IDs
            stmt = select(Service).where(Service.id.in_(service_ids))
            result = await session.execute(stmt)
            services = list(result.scalars().all())

            # Calculate totals
            total_price = sum(s.price_euros for s in services)
            total_duration = sum(s.duration_minutes for s in services)

            logger.info(f"Total calculated: {total_price}€, {total_duration}min")

            return {
                "total_price": total_price,
                "total_duration": total_duration,
                "service_count": len(services),
                "services": services,
            }

    except Exception as e:
        logger.exception(f"Error calculating total: {e}")
        return {
            "total_price": Decimal("0.00"),
            "total_duration": 0,
            "service_count": 0,
            "services": [],
        }


async def validate_service_combination(
    service_ids: list[UUID], session: AsyncSession
) -> dict[str, Any]:
    """
    Validate that requested services are from the same category.

    Args:
        service_ids: List of service UUIDs to validate
        session: Database session

    Returns:
        Dict with validation result:
        - valid: bool (True if same category or single service)
        - reason: str | None ('mixed_categories' if invalid)
        - services_by_category: dict[ServiceCategory, list[Service]] (grouped services)

    Example:
        >>> result = await validate_service_combination([corte_id, color_id], session)
        >>> result["valid"]  # True (both Hairdressing)

        >>> result = await validate_service_combination([corte_id, bioterapia_id], session)
        >>> result["valid"]  # False (Hairdressing + Aesthetics)
    """
    try:
        logger.info(f"Validating service combination: {len(service_ids)} services")

        # Edge case: empty list is valid
        if not service_ids:
            logger.debug("Empty service_ids list, validation passed")
            return {
                "valid": True,
                "reason": None,
                "services_by_category": {},
            }

        # Query all services at once (single DB call)
        stmt = select(Service).where(Service.id.in_(service_ids))
        result = await session.execute(stmt)
        services = list(result.scalars().all())

        # Check for non-existent service IDs
        if len(services) != len(service_ids):
            found_ids = {s.id for s in services}
            missing_ids = set(service_ids) - found_ids
            logger.error(
                f"Service validation failed: {len(missing_ids)} non-existent service_ids: {missing_ids}"
            )
            return {
                "valid": False,
                "reason": "invalid_service_ids",
                "services_by_category": {},
            }

        # Group services by category
        by_category: dict[ServiceCategory, list[Service]] = defaultdict(list)
        for service in services:
            by_category[service.category].append(service)

        # Validation rules
        num_categories = len(by_category)

        # Single service or all same category → valid
        if num_categories <= 1:
            logger.info(f"Validation passed: {num_categories} category")
            return {
                "valid": True,
                "reason": None,
                "services_by_category": dict(by_category),
            }

        # Multiple categories → invalid
        category_names = [cat.value for cat in by_category.keys()]
        logger.warning(
            f"Validation failed: mixed categories detected: {category_names}"
        )
        return {
            "valid": False,
            "reason": "mixed_categories",
            "services_by_category": dict(by_category),
        }

    except Exception as e:
        logger.exception(f"Error validating service combination: {e}")
        return {
            "valid": False,
            "reason": "validation_error",
            "services_by_category": {},
        }


# ============================================================================
# LangChain Tools (for Conversational Agent)
# ============================================================================


@tool(args_schema=GetServicesSchema)
async def get_services(category: str | None = None) -> dict[str, Any]:
    """
    Get all active services, optionally filtered by category.

    Queries the Service table and returns service information including
    name, price, duration, and category.

    Args:
        category: Optional category filter ("Hairdressing" or "Aesthetics")

    Returns:
        Dict with:
        - services: List of service dicts with id, name, price_euros, duration_minutes, category
        - count: Number of services returned

    Example:
        >>> result = await get_services("Hairdressing")
        >>> result["services"]
        [{"id": "...", "name": "Corte", "price_euros": 25.0, ...}, ...]
    """
    try:
        async for session in get_async_session():
            query = select(Service).where(Service.is_active == True)

            # Filter by category if provided
            if category:
                try:
                    category_enum = ServiceCategory[category.upper()]
                    query = query.where(Service.category == category_enum)
                except KeyError:
                    logger.warning(f"Invalid category: {category}")

            result = await session.execute(query)
            services = list(result.scalars().all())

        services_list = [
            {
                "id": str(service.id),
                "name": service.name,
                "price_euros": float(service.price_euros),
                "duration_minutes": service.duration_minutes,
                "category": service.category.value,
            }
            for service in services
        ]

        logger.info(
            f"Retrieved {len(services_list)} services" +
            (f" for category: {category}" if category else "")
        )

        return {
            "services": services_list,
            "count": len(services_list),
        }

    except Exception as e:
        logger.error(f"Error in get_services: {e}", exc_info=True)
        return {
            "services": [],
            "count": 0,
            "error": "Error consultando servicios",
        }


# ============================================================================
# Booking Flow Initiation Tool
# ============================================================================


class StartBookingFlowSchema(BaseModel):
    """Schema for start_booking_flow tool parameters."""

    services: list[str] = Field(
        description="Lista de servicios que el cliente quiere reservar (nombres o IDs)"
    )
    preferred_date: str | None = Field(
        default=None,
        description="Fecha preferida del cliente (ej: '2025-11-01', 'viernes', 'mañana')"
    )
    preferred_time: str | None = Field(
        default=None,
        description="Hora preferida del cliente (ej: '15:00', 'por la tarde', 'mañana')"
    )
    notes: str | None = Field(
        default=None,
        description="Notas adicionales del cliente sobre la reserva"
    )


@tool(args_schema=StartBookingFlowSchema)
async def start_booking_flow(
    services: list[str],
    preferred_date: str | None = None,
    preferred_time: str | None = None,
    notes: str | None = None
) -> dict[str, Any]:
    """
    Inicia el flujo transaccional de reserva de cita (INTENT DETECTION ONLY).

    ⚠️ IMPORTANTE: Esta herramienta es SOLO para detectar intención de reserva.
    El sistema automáticamente:
    1. Resuelve los nombres de servicios a UUIDs en la base de datos
    2. Actualiza el estado con requested_services
    3. Transfiere a Tier 2 (flujo transaccional)

    CUÁNDO USAR ESTA HERRAMIENTA:
    ✅ USA cuando el cliente exprese intención CLARA de reservar:
       - "Quiero reservar mechas para el viernes"
       - "Dame cita para corte"
       - "Perfecto, agéndame"
       - "Sí, quiero reservar"
       - "¿Tenéis libre el viernes? Si hay, reservo" (con confirmación)

    ❌ NO LA USES si el cliente solo está consultando:
       - "¿Cuánto cuesta?" → NO (solo consulta precio)
       - "¿Tenéis libre?" → NO (a menos que diga "si hay, reserva")
       - "¿Qué incluye el pack?" → NO (aún comparando)
       - Cliente indeciso o preguntando opciones → NO

    CRITERIO CLAVE: El cliente debe expresar COMPROMISO de reservar,
    no solo curiosidad o consulta informativa.

    Args:
        services: Lista de nombres de servicios solicitados (ej: ["mechas", "corte"])
                  El sistema los resolverá automáticamente a UUIDs.
        preferred_date: Fecha preferida en cualquier formato natural
        preferred_time: Hora preferida en cualquier formato natural
        notes: Notas adicionales sobre preferencias o necesidades especiales

    Returns:
        Dict con confirmación de inicio del flujo y datos capturados.
        Nota: La resolución de servicios a UUIDs ocurre en conversational_agent.py

    Example:
        >>> # Cliente dice: "Quiero mechas y corte para el viernes a las 3"
        >>> result = await start_booking_flow(
        ...     services=["mechas", "corte"],
        ...     preferred_date="viernes",
        ...     preferred_time="15:00"
        ... )
        >>> # Resultado: {"booking_initiated": True, ...}
        >>> # Sistema automáticamente resuelve "mechas" y "corte" a UUIDs
    """
    logger.info(
        f"Booking flow initiated",
        extra={
            "services": services,
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "has_notes": bool(notes),
        }
    )

    return {
        "booking_initiated": True,
        "services": services,
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
        "notes": notes,
        "message": "Flujo de reserva iniciado. Procederé a validar servicios y verificar disponibilidad.",
    }


# ============================================================================
# Set Preferred Date Tool
# ============================================================================


class SetPreferredDateSchema(BaseModel):
    """Schema for set_preferred_date tool parameters."""

    preferred_date: str = Field(
        description="Fecha preferida del cliente en formato natural (ej: '2025-11-01', 'viernes', 'mañana', '5 de noviembre')"
    )
    preferred_time: str | None = Field(
        default=None,
        description="Hora preferida del cliente si la menciona (ej: '15:00', 'por la tarde', '3 de la tarde')"
    )


@tool(args_schema=SetPreferredDateSchema)
async def set_preferred_date(
    preferred_date: str,
    preferred_time: str | None = None
) -> dict[str, Any]:
    """
    Registra la fecha y hora preferida del cliente para su cita.

    CUÁNDO USAR ESTA HERRAMIENTA:
    ✅ USA cuando el cliente responda con una fecha después de preguntarle:
       - Cliente: "El viernes" → set_preferred_date(preferred_date="viernes")
       - Cliente: "Mañana a las 3" → set_preferred_date(preferred_date="mañana", preferred_time="15:00")
       - Cliente: "5 de noviembre" → set_preferred_date(preferred_date="2025-11-05")

    ❌ NO LA USES si:
       - El cliente aún está preguntando sin confirmar
       - Ya usaste start_booking_flow() con la fecha

    Esta herramienta se usa SOLO cuando el sistema ya preguntó "¿Qué día prefieres?"
    y el cliente está respondiendo con su preferencia.

    Args:
        preferred_date: Fecha preferida en cualquier formato natural
        preferred_time: Hora preferida si el cliente la especifica

    Returns:
        Dict confirmando que la fecha fue registrada

    Example:
        >>> # Sistema preguntó: "¿Qué día prefieres?"
        >>> # Cliente respondió: "El viernes por la tarde"
        >>> result = await set_preferred_date(
        ...     preferred_date="viernes",
        ...     preferred_time="por la tarde"
        ... )
        >>> # Resultado: {"date_set": True, "preferred_date": "viernes", ...}
    """
    logger.info(
        f"Preferred date set by customer",
        extra={
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
        }
    )

    return {
        "date_set": True,
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
        "message": f"Fecha registrada: {preferred_date}" + (f" a las {preferred_time}" if preferred_time else ""),
    }
