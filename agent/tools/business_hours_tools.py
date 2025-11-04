"""
Business hours tools for conversational agent.

Provides access to salon operating hours from database.
"""

import logging
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select

from database.connection import get_async_session
from database.models import BusinessHours

logger = logging.getLogger(__name__)

# Spanish day names mapping
DAY_NAMES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}


@tool
async def get_business_hours() -> dict[str, Any]:
    """
    Get salon business hours from database.

    Retrieves operating hours for each day of the week (Monday-Sunday).
    Returns formatted schedule suitable for customer communication.

    Returns:
        Dict with:
        - schedule: List of dicts with day, is_closed, hours
        - formatted: Human-readable Spanish schedule summary
        - raw_days: List of raw day data for programmatic use

    Example:
        >>> result = await get_business_hours()
        >>> result["formatted"]
        "Martes a Viernes: 10:00-20:00, Sábado: 09:00-14:00, Lunes y Domingo: Cerrado"
    """
    try:
        async for session in get_async_session():
            # Query all days ordered by day_of_week
            query = select(BusinessHours).order_by(BusinessHours.day_of_week)
            result = await session.execute(query)
            hours = list(result.scalars().all())
            break

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
                    "hours": f"{start_time} - {end_time}",
                })

        # Generate formatted summary
        formatted = _format_schedule_summary(schedule)

        logger.info("Retrieved business hours successfully")

        return {
            "schedule": schedule,
            "formatted": formatted,
            "raw_days": schedule,  # Alias for compatibility
        }

    except Exception as e:
        logger.error(f"Error in get_business_hours: {e}", exc_info=True)
        return {
            "schedule": [],
            "formatted": "Error consultando horarios",
            "error": str(e),
        }


def _format_schedule_summary(schedule: list[dict]) -> str:
    """
    Format schedule into human-readable Spanish summary.

    Groups consecutive days with same hours for concise presentation.

    Args:
        schedule: List of day schedule dicts

    Returns:
        Formatted string like "Martes a Viernes: 10:00-20:00, Sábado: 09:00-14:00"
    """
    if not schedule:
        return "No hay horarios disponibles"

    # Group days by hours
    groups = []
    current_group = None

    for day_data in schedule:
        if current_group is None:
            # Start first group
            current_group = {
                "days": [day_data["day"]],
                "hours": day_data["hours"],
            }
        elif day_data["hours"] == current_group["hours"]:
            # Same hours, add to current group
            current_group["days"].append(day_data["day"])
        else:
            # Different hours, close current group and start new one
            groups.append(current_group)
            current_group = {
                "days": [day_data["day"]],
                "hours": day_data["hours"],
            }

    # Add last group
    if current_group:
        groups.append(current_group)

    # Format each group
    formatted_groups = []
    for group in groups:
        days = group["days"]
        hours = group["hours"]

        if len(days) == 1:
            # Single day: "Lunes: 10:00-20:00"
            formatted_groups.append(f"{days[0]}: {hours}")
        else:
            # Multiple consecutive days: "Martes a Viernes: 10:00-20:00"
            formatted_groups.append(f"{days[0]} a {days[-1]}: {hours}")

    return ", ".join(formatted_groups)
