"""
Prompt loading utilities for the Maite agent.

This module provides functions to load system prompts from disk and
inject dynamic context (e.g., stylist team data, business settings) from the database.

v4.0: Added modular prompt system with Jinja2 templating and dynamic variable injection.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from database.connection import get_async_session
from database.models import Stylist, ServiceCategory
from sqlalchemy import select

# Import shared cache (safe for both API and Agent)
from shared.stylist_cache import get_cache, clear_stylist_context_cache

# Import dynamic context loader
from agent.prompts.dynamic_context import clear_dynamic_context_cache

logger = logging.getLogger(__name__)

# Global cache for stylist context with TTL (10 minutes)
# This reduces database queries and improves OpenRouter cache hit rate
# Cache data is stored in shared module, lock is local to agent
_STYLIST_CONTEXT_CACHE = get_cache()
_STYLIST_CONTEXT_CACHE["lock"] = asyncio.Lock()


def load_maite_system_prompt() -> str:
    """
    Load the Maite system prompt from disk.

    Returns:
        str: The complete system prompt text.

    Raises:
        No exceptions raised - returns fallback prompt on errors.
    """
    prompt_path = Path(__file__).parent / "legacy" / "maite_system_prompt.md"
    fallback_prompt = (
        "Eres Maite, asistente virtual de Atrevete Peluqueria. "
        "Se amable, usa herramientas, y escala cuando sea necesario."
    )

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()

        if len(prompt) < 100:
            logger.error(f"System prompt too short ({len(prompt)} characters), using fallback")
            return fallback_prompt

        logger.info(f"Loaded Maite system prompt ({len(prompt)} characters)")
        return prompt

    except FileNotFoundError:
        logger.error(f"System prompt file not found at {prompt_path}, using fallback")
        return fallback_prompt

    except IOError as e:
        logger.error(f"Error reading system prompt file: {e}, using fallback")
        return fallback_prompt

    except Exception as e:
        logger.error(f"Unexpected error loading system prompt: {e}, using fallback")
        return fallback_prompt


async def load_stylist_context() -> str:
    """
    Load active stylists from database with 10-minute in-memory caching.

    This function queries the database for all active stylists and formats them
    into a markdown section that can be injected into the system prompt dynamically.
    Uses a 10-minute TTL cache to reduce database load and improve performance.

    Caching Strategy:
    - First request: Query database (~150ms) and cache result for 10 minutes
    - Subsequent requests: Return cached data (0ms) until expiration
    - Trade-off: Stylist data may be up to 10 minutes stale (acceptable, rarely changes)

    Returns:
        str: Formatted markdown string with stylist team information grouped by category.
             Example:
             ```
             ### Equipo de Estilistas (6 profesionales)

             **Peluquería:**
             - Ana (ID: 550e8400...)
             - Marta (ID: 771f48a9...)

             **Estética:**
             - Rosa (ID: 9a4d5e2f...)
             ```

    Raises:
        No exceptions raised - returns fallback message on errors.
    """
    now = datetime.now()

    # Check cache validity (with async lock to prevent race conditions)
    async with _STYLIST_CONTEXT_CACHE["lock"]:
        if (
            _STYLIST_CONTEXT_CACHE["data"] is not None
            and _STYLIST_CONTEXT_CACHE["expires_at"] is not None
            and _STYLIST_CONTEXT_CACHE["expires_at"] > now
        ):
            logger.debug("Using cached stylist context (cache hit)")
            return _STYLIST_CONTEXT_CACHE["data"]

        # Cache miss or expired - query database
        logger.info("Cache miss - loading stylist context from database")

        try:
            stylists_by_category = {"Peluquería": [], "Estética": []}

            async with get_async_session() as session:
                stmt = (
                    select(Stylist)
                    .where(Stylist.is_active == True)  # noqa: E712
                    .order_by(Stylist.name)
                )
                result = await session.execute(stmt)
                stylists = result.scalars().all()

                for stylist in stylists:
                    category_es = (
                        "Peluquería"
                        if stylist.category == ServiceCategory.HAIRDRESSING
                        else "Estética"
                    )
                    # Store dict with name and UUID for prompt injection
                    stylists_by_category[category_es].append(
                        {"name": stylist.name, "id": str(stylist.id)}
                    )

            # Count total stylists
            total_count = sum(len(names) for names in stylists_by_category.values())

            # Format for prompt injection with UUIDs
            context = f"### Equipo de Estilistas ({total_count} profesionales)\n\n"
            context += "**Peluquería:**\n"
            if stylists_by_category["Peluquería"]:
                for stylist in stylists_by_category["Peluquería"]:
                    # Include full UUID for LLM tool calls
                    context += f"- {stylist['name']} (ID: {stylist['id']})\n"
                context += "\n"
            else:
                context += "- (Ninguno activo)\n\n"

            context += "**Estética:**\n"
            if stylists_by_category["Estética"]:
                for stylist in stylists_by_category["Estética"]:
                    # Include full UUID for LLM tool calls
                    context += f"- {stylist['name']} (ID: {stylist['id']})\n"
            else:
                context += "- (Ninguno activo)"

            # Update cache with 10-minute TTL
            _STYLIST_CONTEXT_CACHE["data"] = context
            _STYLIST_CONTEXT_CACHE["expires_at"] = now + timedelta(minutes=10)

            logger.info(f"Stylist context cached (TTL: 10 min, {total_count} active stylists)")
            return context

        except Exception as e:
            logger.error(f"Error loading stylist context from database: {e}", exc_info=True)
            # Fallback to generic message if database query fails
            fallback = (
                "### Equipo de Estilistas\n\n"
                "Contamos con un equipo de estilistas profesionales especializados "
                "en peluquería y estética. Consulta disponibilidad para ver quién "
                "puede atenderte."
            )

            # Don't cache fallback message
            return fallback


# Import loader functions for v6.1 optimized prompt system
# These provide modular shared prompts with caching
try:
    from agent.prompts.loader import (
        load_markdown,
        get_system_prompt,
        clear_prompt_cache,
        build_layered_messages,
    )

    LOADER_AVAILABLE = True
except ImportError:
    LOADER_AVAILABLE = False

__all__ = [
    # Legacy functions (v3.x - v6.0)
    "load_maite_system_prompt",
    "load_stylist_context",
    "clear_stylist_context_cache",
    "clear_dynamic_context_cache",
    # v6.1 optimized prompt system (new)
    "load_markdown",
    "get_system_prompt",
    "clear_prompt_cache",
    "build_layered_messages",
    "LOADER_AVAILABLE",
]
