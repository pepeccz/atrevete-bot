"""PromptAssemblyMiddleware — assemble XML slots into system_message.

Reads _slot_* keys written by upstream middlewares and appends them
to system_message.content in SLOT_REGISTRY order (defined in agent.state):
  1. _slot_today
  2. _slot_customer
  3. _slot_upcoming_appointments
  4. _slot_business_hours
  5. _slot_availability
  6. _slot_catalog

Missing slots are silently skipped.
Must run AFTER DynamicPromptMiddleware and BEFORE SummarizeMiddleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from agent.state import SLOT_REGISTRY

logger = logging.getLogger(__name__)


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

        slots_present = [key for key in SLOT_REGISTRY if state.get(key)]

        if not slots_present:
            return await handler(request)

        blocks = [state[key] for key in slots_present]

        original_content = request.system_message.content if request.system_message else ""
        assembled = original_content + "\n\n" + "\n\n".join(blocks)
        new_system = SystemMessage(content=assembled)
        modified_request = request.override(system_message=new_system)

        logger.debug(
            "PromptAssemblyMiddleware: assembled %d slot(s) into system prompt", len(blocks)
        )
        # sdd/context-coherence D10: PII-safe structured log — slot NAMES only,
        # never their content.
        logger.info(
            "prompt_assembly.slots",
            extra={
                "type": "prompt_assembly.slots",
                "conversation_id": state.get("conversation_id"),
                "slots_present": slots_present,
            },
        )

        return await handler(modified_request)
