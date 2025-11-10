"""
Consolidated Information Tools for v3.0 Architecture.

This module consolidates 4 dispersed information tools into a single query_info() tool:
- get_services() (from booking_tools.py)
- get_faqs() (from faq_tools.py)
- get_business_hours() (from business_hours_tools.py)
- get_payment_policies() (from policy_tools.py)

The query_info() tool uses a type parameter to route to the appropriate data source.
"""

import json
import logging
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from database.connection import get_async_session
from database.models import BusinessHours, Policy, Service, ServiceCategory

logger = logging.getLogger(__name__)

# Spanish day names mapping for business hours
DAY_NAMES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}


class QueryInfoSchema(BaseModel):
    """Schema for query_info tool parameters."""

    type: Literal["services", "faqs", "hours", "policies"] = Field(
        description=(
            "Type of information to query:\n"
            "- 'services': Get list of available salon services\n"
            "- 'faqs': Get frequently asked questions/answers\n"
            "- 'hours': Get business hours schedule\n"
            "- 'policies': Get payment and booking policies"
        )
    )

    filters: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional filters for the query:\n"
            "For 'services': {'category': 'Peluquería' | 'Estética'}\n"
            "For 'faqs': {'keywords': ['hours', 'parking', 'address']}"
        )
    )

    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description=(
            "Maximum number of results to return (1-50). Default: 10.\n"
            "Use lower values (5-10) when user asks general questions.\n"
            "Use higher values (20-50) only if user specifically needs complete catalog."
        )
    )

    @field_validator('filters', mode='before')
    @classmethod
    def parse_filters(cls, v):
        """
        Parse filters parameter to accept both dict and JSON string.

        This handles cases where LLMs incorrectly serialize the filters
        parameter as a JSON string instead of a native dict object.
        """
        if v is None:
            return None

        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError as e:
                raise ValueError(f"filters must be a valid JSON string or dict, got invalid JSON: {e}")

        if isinstance(v, dict):
            return v

        raise ValueError(f"filters must be a dict or JSON string, got {type(v).__name__}")


@tool(args_schema=QueryInfoSchema)
async def query_info(
    type: Literal["services", "faqs", "hours", "policies"],
    filters: dict[str, Any] | None = None,
    max_results: int = 10
) -> dict[str, Any]:
    """
    Query salon information (services, FAQs, hours, policies) with truncation.

    This consolidated tool provides access to all salon information through a single interface.
    Use the 'type' parameter to specify what information you need.

    **v3.2 Enhancement**: Added max_results parameter to reduce token usage. Default: 10 items.

    Args:
        type: Type of information to query:
            - "services": Available salon services with prices/durations
            - "faqs": Frequently asked questions and answers
            - "hours": Business hours schedule
            - "policies": Payment and booking policies
        filters: Optional filters dict:
            - For services: {"category": "Peluquería" | "Estética"}
            - For faqs: {"keywords": ["hours", "parking"]}
        max_results: Maximum results to return (1-50). Default: 10.

    Returns:
        Dict with queried data. Structure varies by type:

        services:
            {
                "count": int
            }

        faqs:
            {
                "faqs": [{"category": str, "question": str, "answer": str}],
                "count": int
            }

        hours:
            {
                "schedule": [{"day": str, "is_closed": bool, "hours": str}],
                "formatted": str  # Human-readable summary
            }

        policies:
            {
                "advance_payment_percentage": int,
                "provisional_timeout_standard": int,
                "provisional_timeout_same_day": int,
                "formatted": str
            }

    Examples:
        Get all services:
        >>> await query_info("services")
        {"services": [{"name": "Corte de Caballero", ...}], "count": 92}

        Get Peluquería services only:
        >>> await query_info("services", {"category": "Peluquería"})
        {"services": [...], "count": 65}

        Get FAQs about hours and parking:
        >>> await query_info("faqs", {"keywords": ["hours", "parking"]})
        {"faqs": [{"question": "¿A qué hora abrís?", "answer": "..."}], "count": 2}

        Get business hours:
        >>> await query_info("hours")
        {"schedule": [...], "formatted": "Martes a Viernes: 10:00-20:00, ..."}

        Get payment policies:
        >>> await query_info("policies")
        {"advance_payment_percentage": 20, ...}
    """
    try:
        if type == "services":
            return await _get_services(filters, max_results)
        elif type == "faqs":
            return await _get_faqs(filters, max_results)
        elif type == "hours":
            return await _get_business_hours()
        elif type == "policies":
            return await _get_payment_policies()
        else:
            logger.error(f"Invalid query type: {type}")
            return {"error": f"Invalid type: {type}"}

    except Exception as e:
        logger.error(f"Error in query_info(type={type}): {e}", exc_info=True)
        return {"error": f"Error querying {type}"}


async def _get_services(filters: dict[str, Any] | None, max_results: int = 10) -> dict[str, Any]:
    """
    Get active services with optional filtering and truncation (v3.2).

    Internal function called by query_info(type="services").

    Args:
        filters: Optional category filter
        max_results: Maximum results to return (default: 10)

    Returns:
        Dict with truncated services list, count_shown, and count_total
    """
    async for session in get_async_session():
        query = select(Service).where(Service.is_active == True)

        # Filter by category if provided
        if filters and "category" in filters:
            category_value = filters["category"]
            # Convert to ServiceCategory enum value
            if category_value in ["Peluquería", "PELUQUERIA", "HAIRDRESSING"]:
                query = query.where(Service.category == ServiceCategory.HAIRDRESSING)
            elif category_value in ["Estética", "ESTETICA", "AESTHETICS"]:
                query = query.where(Service.category == ServiceCategory.AESTHETICS)

        query = query.order_by(Service.category, Service.name)

        result = await session.execute(query)
        services = list(result.scalars().all())

        # Truncate to max_results
        total_count = len(services)
        truncated_services = services[:max_results]

        logger.info(
            f"Retrieved {len(truncated_services)}/{total_count} services" +
            (f" for category {filters.get('category')}" if filters else "") +
            (f" (truncated to {max_results})" if total_count > max_results else "")
        )

        return {
            "services": [
                {
                    "name": s.name,  # Simplified: removed id to save tokens
                    "duration_minutes": s.duration_minutes,
                    "category": s.category.value,
                }
                for s in truncated_services
            ],
            "count_shown": len(truncated_services),
            "count_total": total_count,
            "note": (
                f"Showing {len(truncated_services)} of {total_count} services. "
                "Ask user to be more specific if needed."
                if total_count > max_results else None
            )
        }
        break


async def _get_faqs(filters: dict[str, Any] | None, max_results: int = 10) -> dict[str, Any]:
    """
    Get FAQ/policy information from database with truncation (v3.2).

    Internal function called by query_info(type="faqs").

    Args:
        filters: Optional keyword filters
        max_results: Maximum results to return (default: 10)
    """
    async for session in get_async_session():
        # Filter only FAQ policies (keys starting with 'faq_')
        query = select(Policy).where(Policy.key.like('faq_%'))

        result = await session.execute(query)
        policies = list(result.scalars().all())

        # Parse JSONB value field to extract FAQ data
        faqs = []
        for policy in policies:
            faq_data = policy.value  # JSONB dict with 'question', 'answer', 'keywords'

            # Filter by keywords if provided
            if filters and "keywords" in filters:
                requested_keywords = filters["keywords"]
                faq_keywords = faq_data.get("keywords", [])
                # Check if any requested keyword matches FAQ keywords
                if not any(kw in faq_keywords for kw in requested_keywords):
                    continue

            faqs.append({
                "category": policy.key.replace("faq_", ""),
                "question": faq_data.get("question", ""),
                "answer": faq_data.get("answer", ""),
            })

        # Truncate to max_results
        total_count = len(faqs)
        truncated_faqs = faqs[:max_results]

        logger.info(
            f"Retrieved {len(truncated_faqs)}/{total_count} FAQs" +
            (f" for keywords: {filters.get('keywords')}" if filters else "") +
            (f" (truncated to {max_results})" if total_count > max_results else "")
        )

        return {
            "faqs": truncated_faqs,
            "count_shown": len(truncated_faqs),
            "count_total": total_count,
            "note": (
                f"Showing {len(truncated_faqs)} of {total_count} FAQs. "
                "Refine keywords for more specific results."
                if total_count > max_results else None
            )
        }
        break


async def _get_business_hours() -> dict[str, Any]:
    """
    Get salon business hours from database.

    Internal function called by query_info(type="hours").
    """
    async for session in get_async_session():
        # Query all days ordered by day_of_week
        query = select(BusinessHours).order_by(BusinessHours.day_of_week)
        result = await session.execute(query)
        hours = list(result.scalars().all())

        if not hours:
            logger.warning("No business hours found in database")
            return {
                "schedule": [],
                "formatted": "No hay horarios configurados",
                "error": "No business hours configured",
            }

        # Build schedule data
        schedule = []
        for day_hours in hours:
            day_name = DAY_NAMES.get(day_hours.day_of_week, f"Day {day_hours.day_of_week}")

            if day_hours.is_closed:
                schedule.append({
                    "day": day_name,
                    "day_of_week": day_hours.day_of_week,
                    "is_closed": True,
                    "hours": "Cerrado",
                })
            else:
                start_time = f"{day_hours.start_hour:02d}:{day_hours.start_minute:02d}"
                end_time = f"{day_hours.end_hour:02d}:{day_hours.end_minute:02d}"
                schedule.append({
                    "day": day_name,
                    "day_of_week": day_hours.day_of_week,
                    "is_closed": False,
                    "hours": f"{start_time}-{end_time}",
                    "start_hour": day_hours.start_hour,
                    "start_minute": day_hours.start_minute,
                    "end_hour": day_hours.end_hour,
                    "end_minute": day_hours.end_minute,
                })

        # Format human-readable summary
        formatted = _format_schedule_summary(schedule)

        logger.info("Retrieved business hours")

        return {
            "schedule": schedule,
            "formatted": formatted,
        }
        break


def _format_schedule_summary(schedule: list[dict]) -> str:
    """
    Format business hours into human-readable Spanish summary.

    Groups consecutive days with same hours.
    """
    # Group consecutive days with same hours
    groups = []
    current_group = None

    for day_data in schedule:
        if current_group is None:
            current_group = {
                "days": [day_data["day"]],
                "hours": day_data["hours"],
                "is_closed": day_data["is_closed"]
            }
        elif day_data["hours"] == current_group["hours"]:
            # Same hours, add to current group
            current_group["days"].append(day_data["day"])
        else:
            # Different hours, start new group
            groups.append(current_group)
            current_group = {
                "days": [day_data["day"]],
                "hours": day_data["hours"],
                "is_closed": day_data["is_closed"]
            }

    # Add last group
    if current_group:
        groups.append(current_group)

    # Format each group
    formatted_parts = []
    for group in groups:
        if len(group["days"]) == 1:
            day_str = group["days"][0]
        elif len(group["days"]) == 2:
            day_str = f"{group['days'][0]} y {group['days'][1]}"
        else:
            day_str = f"{group['days'][0]} a {group['days'][-1]}"

        formatted_parts.append(f"{day_str}: {group['hours']}")

    return ", ".join(formatted_parts)


async def _get_payment_policies() -> dict[str, Any]:
    """
    Get payment and booking policies from database.

    Internal function called by query_info(type="policies").
    """
    async for session in get_async_session():
        # Query payment-related policies
        query = select(Policy).where(
            Policy.key.in_([
                "advance_payment_percentage",
                "provisional_timeout_standard",
                "provisional_timeout_same_day",
            ])
        )
        result = await session.execute(query)
        policies = list(result.scalars().all())

        if not policies:
            logger.warning("No payment policies found in database")
            # Return fallback defaults
            return {
                "advance_payment_percentage": 20,
                "provisional_timeout_standard": 30,
                "provisional_timeout_same_day": 10,
                "formatted": "Anticipo: 20% del total. Tiempo para pagar: 30 minutos (10 minutos para citas del mismo día).",
            }

        # Parse policies
        policies_dict = {}
        for policy in policies:
            key = policy.key
            value = policy.value

            # Handle different value types
            if isinstance(value, dict):
                # JSONB with nested data
                policies_dict[key] = value.get("value", value)
            else:
                # Direct integer value
                policies_dict[key] = value

        advance_percentage = policies_dict.get("advance_payment_percentage", 20)
        timeout_standard = policies_dict.get("provisional_timeout_standard", 30)
        timeout_same_day = policies_dict.get("provisional_timeout_same_day", 10)

        # Format human-readable summary
        formatted = (
            f"Anticipo: {advance_percentage}% del total. "
            f"Tiempo para pagar: {timeout_standard} minutos "
            f"({timeout_same_day} minutos para citas del mismo día)."
        )

        logger.info("Retrieved payment policies")

        return {
            "advance_payment_percentage": advance_percentage,
            "provisional_timeout_standard": timeout_standard,
            "provisional_timeout_same_day": timeout_same_day,
            "formatted": formatted,
        }
        break
