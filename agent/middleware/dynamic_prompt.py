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
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from agent.prompts.business_hours import load_business_hours_snapshot
from agent.prompts.catalog_builder import build_catalog_prompt_section

logger = logging.getLogger(__name__)


def _format_hours(hours: dict[str, str]) -> str:
    if not hours:
        return ""
    lines = "\n".join(f"  {day}: {val}" for day, val in sorted(hours.items()))
    body = f"## Horarios\n{lines}"
    return f"<business_hours>\n{body}\n</business_hours>"


def _format_catalog(catalog: str) -> str:
    if not catalog:
        return ""
    return f"<catalog>\n{catalog}\n</catalog>"


class DynamicPromptMiddleware(AgentMiddleware):
    """Injects catalog, business hours, and active booking snapshot into system prompt.

    Async-only: catalog and business-hours loaders are async I/O against the
    DB. Sync variant would require a duplicate sync DB path that the runtime
    never exercises. Opt out of the parity guardrail.
    """

    _allow_single_variant: ClassVar[bool] = True

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
        except Exception:
            logger.warning("Could not load business hours", exc_info=True)
            hours = {}

        # --- Write _slot_* keys (no system_message mutation) ---
        state = request.state or {}
        new_state = {**state}

        catalog_slot = _format_catalog(catalog_section)
        if catalog_slot:
            new_state["_slot_catalog"] = catalog_slot

        hours_slot = _format_hours(hours)
        if hours_slot:
            new_state["_slot_business_hours"] = hours_slot

        modified_request = request.override(state=new_state)

        return await handler(modified_request)
