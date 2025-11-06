"""
Prompt loading utilities for the Maite agent.

This module provides functions to load system prompts from disk and
inject dynamic context (e.g., stylist team data) from the database.
"""

import logging
from pathlib import Path

from database.connection import get_async_session
from database.models import Stylist, ServiceCategory
from sqlalchemy import select

logger = logging.getLogger(__name__)


def load_maite_system_prompt() -> str:
    """
    Load the Maite system prompt from disk.

    Returns:
        str: The complete system prompt text.

    Raises:
        No exceptions raised - returns fallback prompt on errors.
    """
    prompt_path = Path(__file__).parent / "maite_system_prompt.md"
    fallback_prompt = (
        "Eres Maite, asistenta virtual de Atrevete Peluqueria. "
        "Se amable, usa herramientas, y escala cuando sea necesario."
    )

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()

        if len(prompt) < 100:
            logger.error(
                f"System prompt too short ({len(prompt)} characters), using fallback"
            )
            return fallback_prompt

        logger.info(f"Loaded Maite system prompt ({len(prompt)} characters)")
        return prompt

    except FileNotFoundError:
        logger.error(
            f"System prompt file not found at {prompt_path}, using fallback"
        )
        return fallback_prompt

    except IOError as e:
        logger.error(
            f"Error reading system prompt file: {e}, using fallback"
        )
        return fallback_prompt

    except Exception as e:
        logger.error(
            f"Unexpected error loading system prompt: {e}, using fallback"
        )
        return fallback_prompt


async def load_stylist_context() -> str:
    """
    Load active stylists from database and format for system prompt injection.

    This function queries the database for all active stylists and formats them
    into a markdown section that can be injected into the system prompt dynamically.
    This ensures the prompt always reflects the current team composition.

    Returns:
        str: Formatted markdown string with stylist team information grouped by category.
             Example:
             ```
             ### Equipo de Estilistas (6 profesionales)

             **Peluquería:**
             - Ana
             - Marta
             - Pilar

             **Estética:**
             - Rosa
             ```

    Raises:
        No exceptions raised - returns fallback message on errors.
    """
    try:
        stylists_by_category = {
            "Peluquería": [],
            "Estética": []
        }

        async for session in get_async_session():
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
                stylists_by_category[category_es].append({
                    "name": stylist.name,
                    "id": str(stylist.id)
                })

            break  # Exit async for loop after first iteration

        # Count total stylists
        total_count = sum(len(names) for names in stylists_by_category.values())

        # Format for prompt injection with UUIDs
        context = f"### Equipo de Estilistas ({total_count} profesionales)\n\n"
        context += "**Peluquería:**\n"
        if stylists_by_category["Peluquería"]:
            for stylist in stylists_by_category["Peluquería"]:
                # Include first 8 chars of UUID for readability
                context += f"- {stylist['name']} (ID: {stylist['id'][:8]}...)\n"
            context += "\n"
        else:
            context += "- (Ninguno activo)\n\n"

        context += "**Estética:**\n"
        if stylists_by_category["Estética"]:
            for stylist in stylists_by_category["Estética"]:
                context += f"- {stylist['name']} (ID: {stylist['id'][:8]}...)\n"
        else:
            context += "- (Ninguno activo)"

        logger.info(f"Loaded dynamic stylist context: {total_count} active stylists with UUIDs")
        return context

    except Exception as e:
        logger.error(f"Error loading stylist context from database: {e}", exc_info=True)
        # Fallback to generic message if database query fails
        return (
            "### Equipo de Estilistas\n\n"
            "Contamos con un equipo de estilistas profesionales especializados "
            "en peluquería y estética. Consulta disponibilidad para ver quién "
            "puede atenderte."
        )


__all__ = ["load_maite_system_prompt", "load_stylist_context"]
