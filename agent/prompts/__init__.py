"""
Prompt loading utilities for the Maite agent.

This module provides functions to load system prompts from disk and
inject dynamic context (e.g., stylist team data) from the database.
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
    prompt_path = Path(__file__).parent / "maite_system_prompt.md"
    fallback_prompt = (
        "Eres Maite, asistente virtual de Atrevete Peluqueria. "
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
            stylists_by_category = {
                "Peluquería": [],
                "Estética": []
            }

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
                    stylists_by_category[category_es].append({
                        "name": stylist.name,
                        "id": str(stylist.id)
                    })

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

            logger.info(
                f"Stylist context cached (TTL: 10 min, {total_count} active stylists)"
            )
            return context

        except Exception as e:
            logger.error(
                f"Error loading stylist context from database: {e}",
                exc_info=True
            )
            # Fallback to generic message if database query fails
            fallback = (
                "### Equipo de Estilistas\n\n"
                "Contamos con un equipo de estilistas profesionales especializados "
                "en peluquería y estética. Consulta disponibilidad para ver quién "
                "puede atenderte."
            )

            # Don't cache fallback message
            return fallback


def _detect_booking_state(state: dict) -> str:
    """
    Detect the exact booking state based on state flags and message history.

    Returns one of 7 booking states:
    - GENERAL: Greetings, FAQs, general inquiries (no booking intent)
    - SERVICE_SELECTION: User wants to book but hasn't selected service yet
    - AVAILABILITY_CHECK: Service selected, needs to check availability
    - CUSTOMER_DATA: Slot selected, needs customer data (name, allergies)
    - BOOKING_CONFIRMATION: Customer data collected, waiting for confirmation
    - BOOKING_EXECUTION: Customer confirmed, ready to execute book()
    - POST_BOOKING: Booking completed, handling confirmations/modifications

    Args:
        state: Conversation state dict with flags and message history

    Returns:
        str: One of the 7 booking states
    """
    # Check flags in order of booking flow progression
    if state.get("appointment_created"):
        return "POST_BOOKING"

    if state.get("booking_confirmed"):
        return "BOOKING_EXECUTION"

    if state.get("customer_data_collected"):
        return "BOOKING_CONFIRMATION"

    if state.get("slot_selected"):
        return "CUSTOMER_DATA"

    if state.get("service_selected"):
        return "AVAILABILITY_CHECK"

    # Check for booking intent in last message
    messages = state.get("messages", [])
    if messages:
        last_message = messages[-1].get("content", "").lower()

        # Keywords indicating booking intent
        booking_keywords = [
            "cita", "reserva", "turno", "hora", "día", "reservar",
            "corte", "tinte", "manicura", "depilación", "masaje",
            "peluquería", "estética", "quiero", "necesito"
        ]

        if any(keyword in last_message for keyword in booking_keywords):
            return "SERVICE_SELECTION"

    return "GENERAL"


def load_contextual_prompt(state: dict) -> str:
    """
    Load modular prompts based on conversation state (v3.2 granular state detection).

    This function reduces prompt size from 27KB to ~7-10KB by loading only relevant sections
    based on the exact booking state. Optimized for OpenRouter's automatic caching (GPT-4.1-mini).

    Args:
        state: Conversation state dict containing flags (customer_data_collected, service_selected, etc.)

    Returns:
        str: Assembled prompt with core + relevant step-specific sections

    Prompt Structure (7 states):
        - core.md: Always loaded (~5KB) - Rules, identity, error handling
        - general.md: GENERAL state - FAQs, greetings, no booking intent
        - step1_service.md: SERVICE_SELECTION state - Help select service
        - step2_availability.md: AVAILABILITY_CHECK state - Check availability
        - step3_customer.md: CUSTOMER_DATA state - Collect customer info
        - step3_5_confirmation.md: BOOKING_CONFIRMATION state - Wait for user confirmation
        - step4_booking.md: BOOKING_EXECUTION state - Execute book()
        - step5_post_booking.md: POST_BOOKING state - Confirmations, modifications
    """
    prompt_dir = Path(__file__).parent
    prompt_parts = []

    # 1. Always load core prompt (rules, identity, error handling)
    try:
        core_path = prompt_dir / "core.md"
        with open(core_path, "r", encoding="utf-8") as f:
            prompt_parts.append(f.read())
        logger.debug("Loaded core.md")
    except Exception as e:
        logger.error(f"Error loading core.md: {e}")
        # Fallback to old prompt if core missing
        return load_maite_system_prompt()

    # 2. Detect current booking state
    booking_state = _detect_booking_state(state)

    # 3. Map states to prompt files
    state_to_file = {
        "GENERAL": "general.md",
        "SERVICE_SELECTION": "step1_service.md",
        "AVAILABILITY_CHECK": "step2_availability.md",
        "CUSTOMER_DATA": "step3_customer.md",
        "BOOKING_CONFIRMATION": "step3_5_confirmation.md",
        "BOOKING_EXECUTION": "step4_booking.md",
        "POST_BOOKING": "step5_post_booking.md"
    }

    step_file = state_to_file.get(booking_state, "general.md")

    # 4. Load the step-specific prompt
    try:
        step_path = prompt_dir / step_file
        with open(step_path, "r", encoding="utf-8") as f:
            prompt_parts.append(f.read())
        logger.debug(f"Loaded {step_file} for state={booking_state}")
    except FileNotFoundError:
        logger.warning(
            f"Step file {step_file} not found for state={booking_state}, "
            f"falling back to general.md"
        )
        # Fallback to general.md if specific step file missing
        try:
            general_path = prompt_dir / "general.md"
            with open(general_path, "r", encoding="utf-8") as f:
                prompt_parts.append(f.read())
        except Exception:
            # If even general.md fails, continue with core only
            logger.error("Could not load general.md fallback")
    except Exception as e:
        logger.warning(f"Error loading {step_file}: {e}, using core only")

    # 5. Assemble final prompt
    final_prompt = "\n\n---\n\n".join(prompt_parts)

    logger.info(
        f"Loaded contextual prompt: {len(final_prompt)} chars "
        f"(state={booking_state}, file={step_file})"
    )

    return final_prompt


__all__ = ["load_maite_system_prompt", "load_stylist_context", "load_contextual_prompt", "clear_stylist_context_cache"]
