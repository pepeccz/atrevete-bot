"""
query_info — FAQ tool for GENERAL mode.

Looks up catalog, business hours, and policies from DB via SalonInfoService.
Pure DB lookup — no LLM calls inside.
Returns JSON-serialized ToolResponse.
"""

import logging
from typing import Literal

from langchain_core.tools import tool

from agent.services.salon_info_service import SalonInfoService
from agent.tools.schemas import ToolResponse

logger = logging.getLogger(__name__)


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
            services = await SalonInfoService.get_services()
            return ToolResponse(
                status="ok",
                payload={"services": services},
            ).model_dump_json()

        if topic == "hours":
            hours = await SalonInfoService.get_hours()
            return ToolResponse(
                status="ok",
                payload={"hours": hours},
            ).model_dump_json()

        if topic == "policies":
            policies = await SalonInfoService.get_policies()
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
