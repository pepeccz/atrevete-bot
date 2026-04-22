"""DynamicPromptMiddleware — Phase 5.3.

Injects per-turn context into the LLM system prompt:
  1. Service catalog (via build_catalog_prompt_section)
  2. Business hours snapshot (via load_business_hours_snapshot)
  3. Active booking context snapshot (when state["booking"] is not None)

Shared between booking leaves and general mode (both use create_agent with this middleware).
Uses the async `awrap_model_call` hook from langchain 1.2.15 AgentMiddleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from agent.prompts.business_hours import load_business_hours_snapshot
from agent.prompts.catalog_builder import build_catalog_prompt_section

logger = logging.getLogger(__name__)


def _format_hours(hours: dict[str, str]) -> str:
    if not hours:
        return ""
    lines = "\n".join(f"  {day}: {val}" for day, val in sorted(hours.items()))
    return f"## Horarios\n{lines}"


def _format_booking_snapshot(booking: dict[str, Any]) -> str:
    """Render the active booking context as a compact status block."""
    if not booking:
        return ""
    lines = ["## Reserva en curso"]
    for key, val in booking.items():
        if key.startswith("_"):
            continue  # skip internal flags
        if val is not None:
            lines.append(f"  {key}: {val}")
    return "\n".join(lines)


class DynamicPromptMiddleware(AgentMiddleware):
    """Injects catalog, business hours, and active booking snapshot into system prompt."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        # --- Build dynamic sections ---
        try:
            catalog_section = await build_catalog_prompt_section()
        except Exception:
            logger.warning("Could not build catalog section", exc_info=True)
            catalog_section = ""

        try:
            hours = await load_business_hours_snapshot()
            hours_section = _format_hours(hours)
        except Exception:
            logger.warning("Could not load business hours", exc_info=True)
            hours_section = ""

        # booking snapshot only when active
        booking = (request.state or {}).get("booking")
        booking_section = _format_booking_snapshot(booking) if booking else ""

        # --- Compose new system message ---
        original_content = request.system_message.content if request.system_message else ""
        injected_parts = [p for p in [catalog_section, hours_section, booking_section] if p]
        if injected_parts:
            injected_block = "\n\n".join(injected_parts)
            new_content = f"{original_content}\n\n{injected_block}"
        else:
            new_content = original_content

        modified_request = request.override(system_message=SystemMessage(content=new_content))

        return await handler(modified_request)
