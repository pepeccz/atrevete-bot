"""
query_info — FAQ tool for GENERAL mode.

Looks up catalog, business hours, and policies from DB.
Pure DB lookup — no LLM calls inside.
Returns JSON-serialized ToolResponse.
"""

import logging
from typing import Literal

from langchain_core.tools import tool

from agent.tools.schemas import ToolResponse

logger = logging.getLogger(__name__)


async def _load_services() -> list[dict]:
    """Load all active services sorted by category then name."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Service

    async with get_async_session() as session:
        result = await session.execute(
            select(Service)
            .where(Service.is_active.is_(True))
            .order_by(Service.category, Service.name)
        )
        services = result.scalars().all()

    return [
        {
            "name": svc.name,
            "audience": svc.audience,
            "category": svc.category.value if svc.category else None,
            "duration_minutes": svc.duration_minutes,
            "description": svc.description,
        }
        for svc in services
    ]


async def _load_hours() -> dict:
    """Load business hours keyed by day_of_week (str)."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import BusinessHours

    async with get_async_session() as session:
        result = await session.execute(select(BusinessHours).order_by(BusinessHours.day_of_week))
        rows = result.scalars().all()

    hours = {}
    for row in rows:
        if row.is_closed:
            hours[str(row.day_of_week)] = {"is_closed": True}
        else:
            hours[str(row.day_of_week)] = {
                "is_closed": False,
                "open": f"{row.start_hour:02d}:{row.start_minute:02d}",
                "close": f"{row.end_hour:02d}:{row.end_minute:02d}",
            }
    return hours


async def _load_policies() -> dict:
    """Load all policies whose key starts with 'faq:'."""
    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Policy

    async with get_async_session() as session:
        result = await session.execute(select(Policy).where(Policy.key.like("faq:%")))
        rows = result.scalars().all()

    return {row.key: row.value for row in rows}


@tool
async def query_info(
    topic: Literal["services", "hours", "policies", "general"],
    detail: str | None = None,
) -> str:
    """
    Answer FAQ queries about the salon catalog, business hours, or policies.

    Args:
        topic: Category of information requested.
            - "services": full active service catalog
            - "hours": daily opening/closing times
            - "policies": FAQ key-value policies
            - "general": unclassified question — defers to LLM
        detail: Optional free-text detail (ignored for most topics).

    Returns:
        JSON-serialized ToolResponse.
    """
    try:
        if topic == "services":
            services = await _load_services()
            return ToolResponse(
                status="ok",
                payload={"services": services},
            ).model_dump_json()

        if topic == "hours":
            hours = await _load_hours()
            return ToolResponse(
                status="ok",
                payload={"hours": hours},
            ).model_dump_json()

        if topic == "policies":
            policies = await _load_policies()
            if not policies:
                return ToolResponse(
                    status="partial",
                    payload={"policies": {}},
                    next_step="defer_to_llm",
                ).model_dump_json()
            return ToolResponse(
                status="ok",
                payload={"policies": policies},
            ).model_dump_json()

        # topic == "general" — defer
        return ToolResponse(
            status="partial",
            next_step="defer_to_llm",
            payload={"detail": detail},
        ).model_dump_json()

    except Exception as exc:
        logger.error("query_info error: %s", exc, exc_info=True)
        return ToolResponse(
            status="rejected",
            errors=[f"Error al consultar información: {exc}"],
        ).model_dump_json()
