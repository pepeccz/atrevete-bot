"""DynamicPromptMiddleware — per-turn context injection.

Injects per-turn context into the LLM system prompt:
  1. Service catalog with UUIDs (via build_catalog_prompt_section)
  2. Business hours snapshot (via load_business_hours_snapshot)
  3. Customer block (name, phone, returning flag) — injected by CustomerResolveMiddleware

Uses the async `awrap_model_call` hook from langchain 1.2.15 AgentMiddleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

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

        # --- Compose new system message ---
        original_content = request.system_message.content if request.system_message else ""
        injected_parts = [p for p in [catalog_section, hours_section] if p]
        if injected_parts:
            injected_block = "\n\n".join(injected_parts)
            new_content = f"{original_content}\n\n{injected_block}"
        else:
            new_content = original_content

        modified_request = request.override(system_message=SystemMessage(content=new_content))

        return await handler(modified_request)
