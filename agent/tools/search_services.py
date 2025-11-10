"""
Search Services Tool for v3.1 Architecture.

This tool provides fuzzy search functionality for salon services, returning
only the most relevant matches (max 5) instead of all services.

Use Cases:
- User query: "corte pelo largo" → Returns top 5 matches
- User query: "tinte rubio" → Returns coloring services

This solves the blank response problem when query_info returns 47 services.
"""

import logging
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process
from sqlalchemy import select

from database.connection import get_async_session
from database.models import Service, ServiceCategory

logger = logging.getLogger(__name__)


class SearchServicesSchema(BaseModel):
    """Schema for search_services tool parameters."""

    query: str = Field(
        description=(
            "Search query string to match against service names. "
            "Examples: 'corte largo', 'tinte rubio', 'manicura francesa'"
        ),
        min_length=1
    )

    category: Literal["Peluquería", "Estética"] | None = Field(
        default=None,
        description=(
            "Optional category filter:\n"
            "- 'Peluquería': Hair services only\n"
            "- 'Estética': Aesthetics services only\n"
            "- None: Search across all categories"
        )
    )

    max_results: int = Field(
        default=5,
        description="Maximum number of results to return (default: 5)",
        ge=1,
        le=10
    )


@tool(args_schema=SearchServicesSchema)
async def search_services(
    query: str,
    category: Literal["Peluquería", "Estética"] | None = None,
    max_results: int = 5
) -> dict[str, Any]:
    """
    Search salon services using fuzzy matching.

    This tool finds the most relevant services based on a search query,
    using RapidFuzz for fuzzy string matching. Returns only the top matches
    (max 5 by default) instead of all services.

    **When to use this tool:**
    - User provides specific service keywords: "corte largo", "tinte rubio"
    - User asks for service recommendations: "qué servicios tienen para..."
    - User describes what they want: "quiero cortarme el pelo"

    **When NOT to use (use query_info instead):**
    - User asks to "list all services"
    - User wants to browse complete category
    - User asks "what services do you offer?" (general inquiry)

    Args:
        query: Search query string (e.g., "corte pelo largo", "manicura")
        category: Optional category filter ("Peluquería" or "Estética")
        max_results: Maximum number of results to return (1-10, default 5)

    Returns:
        Dict with search results:
        {
            "services": [
                {
                    "id": str,
                    "name": str,
                    "price_euros": float,
                    "duration_minutes": int,
                    "category": str,
                    "match_score": int  # 0-100, fuzzy match quality
                }
            ],
            "count": int,
            "query": str
        }

        If no matches found:
        {
            "services": [],
            "count": 0,
            "query": str,
            "message": "No se encontraron servicios que coincidan con '{query}'"
        }

    Examples:
        Search for haircut with styling for long hair:
        >>> await search_services("corte peinado largo")
        {
            "services": [
                {"name": "Corte + Peinado (Largo)", "price_euros": 52.20, ...},
                {"name": "Corte + Tratamiento (Largo)", ...}
            ],
            "count": 2,
            "query": "corte peinado largo"
        }

        Search for hair coloring in Peluquería category:
        >>> await search_services("tinte", category="Peluquería")
        {
            "services": [
                {"name": "Tinte de Raíces", ...},
                {"name": "Mechas", ...}
            ],
            "count": 2
        }

    Notes:
        - Uses RapidFuzz token_set_ratio for matching (handles word order)
        - Minimum match score: 50% (configurable)
        - Case-insensitive matching
        - Handles typos and partial matches
        - Returns results sorted by match score (best first)
    """
    try:
        logger.info(
            f"Searching services with query='{query}', category={category}, max_results={max_results}"
        )

        # Step 1: Fetch all active services from database
        async for session in get_async_session():
            db_query = select(Service).where(Service.is_active == True)

            # Filter by category if provided
            if category:
                if category in ["Peluquería", "PELUQUERIA", "HAIRDRESSING"]:
                    db_query = db_query.where(Service.category == ServiceCategory.HAIRDRESSING)
                elif category in ["Estética", "ESTETICA", "AESTHETICS"]:
                    db_query = db_query.where(Service.category == ServiceCategory.AESTHETICS)

            result = await session.execute(db_query)
            services = list(result.scalars().all())

            logger.info(
                f"Fetched {len(services)} services from database" +
                (f" (category: {category})" if category else "")
            )

            break  # Exit async for loop

        # Step 2: Fuzzy match using RapidFuzz
        if not services:
            logger.warning("No services found in database")
            return {
                "services": [],
                "count": 0,
                "query": query,
                "message": "No hay servicios disponibles en este momento"
            }

        # Prepare choices as dict for fuzzy matching: {service_name: service_object}
        choices_dict = {s.name: s for s in services}

        # Use WRatio scorer: best for natural language queries with fuzzy matching
        # WRatio automatically selects the best comparison method and handles:
        # - Natural variations: "cortarme el pelo" → "Corte de Caballero"
        # - Short queries: "corte" → "Corte de Caballero"
        # - Typos and partial matches
        matches = process.extract(
            query,
            choices_dict.keys(),  # Compare against service names only
            scorer=fuzz.WRatio,
            score_cutoff=45,  # Lower threshold for better recall (natural language)
            limit=max_results
        )

        logger.info(
            f"Found {len(matches)} fuzzy matches for query='{query}' " +
            f"(scorer=WRatio, score_cutoff=45, limit={max_results})"
        )

        # Step 3: Format results
        if not matches:
            return {
                "services": [],
                "count": 0,
                "query": query,
                "message": f"No se encontraron servicios que coincidan con '{query}'"
            }

        # Extract matched services and scores (v3.2: simplified output to save tokens)
        matched_services = []
        for match in matches:
            service_name = match[0]  # Matched service name
            match_score = match[1]  # Fuzzy match score
            service_obj = choices_dict[service_name]  # Get service object from dict

            matched_services.append({
                "name": service_obj.name,
                "duration_minutes": service_obj.duration_minutes,
                "category": service_obj.category.value,
                "match_score": int(match_score)  # Add fuzzy match score for transparency
            })

        logger.info(
            f"Returning {len(matched_services)} services for query='{query}'"
        )

        return {
            "services": matched_services,
            "count": len(matched_services),
            "query": query
        }

    except Exception as e:
        logger.error(
            f"Error in search_services(query='{query}', category={category}): {e}",
            exc_info=True
        )
        return {
            "services": [],
            "count": 0,
            "query": query,
            "error": f"Error al buscar servicios: {str(e)}"
        }
