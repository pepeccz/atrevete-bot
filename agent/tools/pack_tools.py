"""
Pack suggestion tools for conversational agent.

Converts pack_suggestion_nodes.py logic to LangChain @tool for use in
conversational agent architecture.
"""

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.tools.booking_tools import (
    calculate_total,
    get_packs_for_multiple_services,
    get_packs_containing_service,
)

logger = logging.getLogger(__name__)


class SuggestPackSchema(BaseModel):
    """Schema for suggest_pack_tool parameters."""

    service_ids: list[str] = Field(
        description="List of service UUIDs as strings"
    )


@tool(args_schema=SuggestPackSchema)
async def suggest_pack_tool(service_ids: list[str]) -> dict[str, Any]:
    """
    Find money-saving packs for requested services.

    Queries the Pack table to find packs that contain the requested services
    and calculates potential savings for the customer.

    Args:
        service_ids: List of service UUIDs as strings

    Returns:
        Dict with:
        - pack_found: Boolean indicating if pack exists
        - pack_name: Name of the pack (if found)
        - pack_id: UUID of the pack as string (if found)
        - pack_price: Pack price in euros (if found)
        - individual_price: Total price of individual services
        - savings: Amount saved with pack in euros (if found)
        - pack_services: List of service names included in pack

    Example:
        >>> result = await suggest_pack_tool([mechas_id, corte_id])
        >>> result["pack_found"]
        True
        >>> result["savings"]
        10.0
    """
    try:
        # Validate inputs
        if not service_ids:
            logger.warning("suggest_pack_tool called with empty service_ids")
            return {
                "pack_found": False,
                "error": "No services provided",
            }

        # Convert string UUIDs to UUID objects
        try:
            service_uuids = [UUID(sid) for sid in service_ids]
        except ValueError as e:
            logger.error(f"Invalid UUID format in service_ids: {e}")
            return {
                "pack_found": False,
                "error": "Invalid service ID format",
            }

        # Calculate individual service total
        individual_total_data = await calculate_total(service_uuids)
        individual_price = float(individual_total_data["total_price"])
        services = individual_total_data["services"]

        # Query packs
        # Strategy 1: Try exact match first (most common case)
        packs = await get_packs_for_multiple_services(service_uuids)

        # Strategy 2: If no exact match, try packs containing any of the services
        if not packs and len(service_uuids) == 1:
            packs = await get_packs_containing_service(service_uuids[0])

        if not packs:
            logger.info(f"No packs found for services: {service_ids}")
            return {
                "pack_found": False,
                "individual_price": individual_price,
                "services": [s.name for s in services],
            }

        # Select best pack (first one if multiple)
        pack = packs[0]

        # Calculate savings
        pack_price = float(pack.price_euros)
        savings = individual_price - pack_price

        # Get pack service names (requires querying services)
        from database.models import Service
        from database.connection import get_async_session
        from sqlalchemy import select

        async for session in get_async_session():
            pack_services_query = select(Service).where(
                Service.id.in_(pack.included_service_ids)
            )
            result = await session.execute(pack_services_query)
            pack_services = list(result.scalars().all())

        logger.info(
            f"Pack found: {pack.name} | "
            f"Individual: {individual_price}€ | "
            f"Pack: {pack_price}€ | "
            f"Savings: {savings}€"
        )

        return {
            "pack_found": True,
            "pack_name": pack.name,
            "pack_id": str(pack.id),
            "pack_price": pack_price,
            "individual_price": individual_price,
            "savings": savings,
            "pack_services": [s.name for s in pack_services],
            "requested_services": [s.name for s in services],
        }

    except Exception as e:
        logger.error(f"Error in suggest_pack_tool: {e}", exc_info=True)
        return {
            "pack_found": False,
            "error": "Error buscando packs",
        }
