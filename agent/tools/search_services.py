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

# ============================================================================
# SPANISH SERVICE SYNONYMS (Fallback for LLM normalization)
# ============================================================================
# Maps common Spanish verb forms and colloquial terms to service nouns.
# This is a fallback in case LLM doesn't normalize correctly in intent_extractor.
# The LLM should handle most cases, but this provides defense-in-depth.
SPANISH_SERVICE_SYNONYMS: dict[str, str] = {
    # Verb forms → service nouns
    "teñir": "tinte color",
    "teñirme": "tinte color",
    "teñirmelo": "tinte color",
    "teñido": "tinte color",
    "pintarme": "tinte color",
    "pintármelo": "tinte color",
    "cortar": "corte",
    "cortarme": "corte",
    "cortármelo": "corte",
    "peinar": "peinado",
    "peinarme": "peinado",
    "depilar": "depilación",
    "depilarme": "depilación",
    "maquillar": "maquillaje",
    "maquillarme": "maquillaje",
    "alisar": "alisado",
    "alisarme": "alisado",
    "rizar": "permanente",
    "rizarme": "permanente",
    # Colloquial terms
    "raparme": "corte rapado",
    "pelo": "",  # Remove generic "pelo" as it adds noise
    "cabello": "",  # Remove generic "cabello"
}


def _expand_synonyms(query: str) -> str:
    """
    Expand query terms using synonym mapping.

    This is a fallback for cases where LLM didn't normalize verb forms
    in the intent_extractor. It maps common Spanish verb forms to
    service nouns for better fuzzy matching.

    Args:
        query: Original search query

    Returns:
        Expanded query with synonyms applied

    Example:
        >>> _expand_synonyms("teñir pelo")
        "tinte color"
    """
    words = query.lower().split()
    expanded = []

    for word in words:
        synonym = SPANISH_SERVICE_SYNONYMS.get(word)
        if synonym is not None:
            if synonym:  # Non-empty synonym
                expanded.append(synonym)
            # Empty synonym = skip word (e.g., "pelo")
        else:
            expanded.append(word)

    result = " ".join(expanded)

    if result != query.lower():
        logger.info(f"Synonym expansion: '{query}' → '{result}'")

    return result


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
                    "name": str,
                    "duration_minutes": int,
                    "category": str,
                    "match_score": int  # 0-100, fuzzy match quality
                }
            ],
            "count": int,
            "query": str
        }

        Note: v3.2 optimization removed price_euros and id fields to reduce token usage.

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
                {"name": "Corte + Peinado (Largo)", "duration_minutes": 60, ...},
                {"name": "Corte + Tratamiento (Largo)", "duration_minutes": 90, ...}
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
        async with get_async_session() as session:
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


        # Step 2: Fuzzy match using RapidFuzz
        if not services:
            logger.warning("No services found in database")
            return {
                "services": [],
                "count": 0,
                "query": query,
                "message": "No hay servicios disponibles en este momento"
            }

        # Prepare choices for fuzzy matching: include name + description for better matching
        # This allows "mechas" to match services where description mentions "mechas"
        # Format: "Service Name | Description excerpt..." for search, mapped back to service
        search_strings: dict[str, Service] = {}
        for s in services:
            # Combine name + description (truncated) for comprehensive matching
            if s.description:
                search_text = f"{s.name} | {s.description[:100]}"
            else:
                search_text = s.name
            search_strings[search_text] = s

        # Apply synonym expansion (fallback for LLM normalization)
        # This handles cases like "teñir pelo" → "tinte color" if LLM didn't normalize
        expanded_query = _expand_synonyms(query)

        # Use WRatio scorer: best for natural language queries with fuzzy matching
        # WRatio automatically selects the best comparison method and handles:
        # - Natural variations: "cortarme el pelo" → "Corte de Caballero"
        # - Short queries: "corte" → "Corte de Caballero"
        # - Typos and partial matches
        matches = process.extract(
            expanded_query,  # Use expanded query with synonyms applied
            search_strings.keys(),  # Compare against name + description
            scorer=fuzz.WRatio,
            score_cutoff=55,  # Balanced threshold: filters noise while allowing fuzzy matches
            limit=max_results
        )

        logger.info(
            f"Found {len(matches)} fuzzy matches | original='{query}' | expanded='{expanded_query}' | "
            f"scorer=WRatio | score_cutoff=55 | limit={max_results}"
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
            search_text = match[0]  # Matched search string (name | description)
            match_score = match[1]  # Fuzzy match score
            service_obj = search_strings[search_text]  # Get service object from mapping

            matched_services.append({
                "name": service_obj.name,
                "description": service_obj.description[:150] if service_obj.description else None,
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
