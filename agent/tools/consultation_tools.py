"""
Consultation offering tools for conversational agent.

Handles free 15-minute consultation offering when customer shows indecision.
"""

import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from database.connection import get_async_session
from database.models import Service

logger = logging.getLogger(__name__)

# Consultation service name constant
CONSULTATION_SERVICE_NAME = "CONSULTA GRATUITA"


class OfferConsultationSchema(BaseModel):
    """Schema for offer_consultation_tool parameters."""

    reason: str = Field(
        description="Brief description of why consultation is being offered (e.g., 'comparing mechas vs balayage')"
    )


@tool(args_schema=OfferConsultationSchema)
async def offer_consultation_tool(reason: str) -> dict[str, Any]:
    """
    Offer free 15-minute consultation when customer is indecisive.

    Queries the database for the free consultation service and returns
    its details so the conversational agent can offer it naturally.

    Args:
        reason: Brief description of indecision reason for logging

    Returns:
        Dict with:
        - consultation_service_id: UUID of consultation service as string
        - duration_minutes: Duration of consultation (15)
        - price_euros: Price of consultation (0)
        - service_name: Name of the service
        - error: Error message if consultation service not found

    Example:
        >>> result = await offer_consultation_tool("comparing mechas vs balayage")
        >>> result["duration_minutes"]
        15
        >>> result["price_euros"]
        0
    """
    try:
        logger.info(f"Offering consultation for reason: {reason}")

        # Query consultation service from database
        async for session in get_async_session():
            query = select(Service).where(
                Service.name.ilike(f"%{CONSULTATION_SERVICE_NAME}%"),
                Service.is_active == True
            )
            result = await session.execute(query)
            consultation_service = result.scalar_one_or_none()

        if not consultation_service:
            logger.error("Consultation service not found in database")
            return {
                "error": "Servicio de consulta no encontrado",
                "consultation_service_id": None,
                "duration_minutes": 15,  # Fallback default
                "price_euros": 0,
            }

        logger.info(
            f"Consultation service found: {consultation_service.name} | "
            f"ID: {consultation_service.id} | "
            f"Duration: {consultation_service.duration_minutes}min"
        )

        return {
            "consultation_service_id": str(consultation_service.id),
            "duration_minutes": consultation_service.duration_minutes,
            "price_euros": float(consultation_service.price_euros),
            "service_name": consultation_service.name,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error in offer_consultation_tool: {e}", exc_info=True)
        return {
            "error": "Error ofreciendo consulta",
            "consultation_service_id": None,
            "duration_minutes": 15,
            "price_euros": 0,
        }
