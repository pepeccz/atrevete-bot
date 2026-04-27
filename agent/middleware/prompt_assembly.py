"""PromptAssemblyMiddleware — assemble XML slots into system_message.

Reads _slot_* keys written by upstream middlewares and appends them
to system_message.content in fixed order:
  1. _slot_customer          → <customer>...</customer>
  2. _slot_upcoming_appointments → <upcoming_appointments>...</upcoming_appointments>
  3. _slot_business_hours    → <business_hours>...</business_hours>
  4. _slot_catalog           → <catalog>...</catalog>

Missing slots are silently skipped.
Must run AFTER DynamicPromptMiddleware and BEFORE SummarizeMiddleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)

_SLOT_ORDER = [
    "_slot_today",
    "_slot_customer",
    "_slot_upcoming_appointments",
    "_slot_business_hours",
    "_slot_catalog",
]


class PromptAssemblyMiddleware(AgentMiddleware):
    """Assemble XML-fenced slot keys into system_message.content.

    Async-only: all upstream slot-writing middlewares are async-only.
    Opt out of the parity guardrail.
    """

    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state or {}

        blocks = [state[key] for key in _SLOT_ORDER if state.get(key)]

        if not blocks:
            return await handler(request)

        original_content = request.system_message.content if request.system_message else ""
        assembled = original_content + "\n\n" + "\n\n".join(blocks)
        new_system = SystemMessage(content=assembled)
        modified_request = request.override(system_message=new_system)

        logger.debug(
            "PromptAssemblyMiddleware: assembled %d slot(s) into system prompt", len(blocks)
        )

        return await handler(modified_request)
