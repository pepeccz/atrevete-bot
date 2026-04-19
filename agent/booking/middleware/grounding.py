"""BookingGroundingMiddleware — injects a fresh ``[grounding]`` HumanMessage before each LLM call.

Calls ``compute_next_prompt(state)`` (pure function in ``agent/booking/grounding.py``) with the
current conversation state (via a zero-arg ``get_state_fn`` closure) and injects the resulting
GroundingDirective as a ``HumanMessage`` whose content starts with ``[grounding]``.

Dedup algorithm (R4):
  - Scans ``request.messages`` from the tail looking for the last ``HumanMessage`` whose
    content starts with ``"[grounding]"``.
  - If found, REPLACES it in-place (prevents accretion across loop iterations).
  - If not found, APPENDS the new message at the tail.

Mode guard (design §5.1):
  - If ``state.get("current_mode") != mode_name``, the request passes through unchanged.
  - Allows safe inclusion in other mode stacks without behavioral impact.

Error handling (design §5.1 — fail-open):
  - Any exception in ``compute_next_prompt`` or ``get_state_fn`` is caught, logged as
    ``booking_grounding.error``, and the request passes through unchanged. This degrades
    gracefully to legacy LLM behavior for that turn rather than crashing.

Observability (design §9):
  - Emits ``booking_grounding.injected`` with fields:
    action, next_action (mandatory_next_call), state_snapshot_keys, dedup.
  - Emits ``booking_grounding.error`` with exception details on failure.

Design refs: design §5.1, §9
Requirements: R4, R5
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage

from agent.booking.grounding import compute_next_prompt

logger = logging.getLogger(__name__)

_GROUNDING_PREFIX = "[grounding]"


class BookingGroundingMiddleware(AgentMiddleware):
    """Inject a fresh ``[grounding]`` HumanMessage before each LLM model call.

    Args:
        get_state_fn: Zero-arg callable that returns the current ConversationState dict.
            Called on EVERY model call so it always reflects the latest state
            (mid-loop tool mutations included).
        mode_name: The mode this middleware is active for (e.g. ``"BOOKING"``).
            If ``state["current_mode"] != mode_name``, the request is passed through
            unchanged (design §5.1 mode-guard isolation).
    """

    def __init__(
        self,
        get_state_fn: Callable[[], dict],
        mode_name: str = "BOOKING",
    ) -> None:
        super().__init__()
        self._get_state_fn = get_state_fn
        self._mode_name = mode_name

    # ── Core injection logic ────────────────────────────────────────────────

    def _inject(self, request: ModelRequest) -> ModelRequest:
        """Return a new ModelRequest with the ``[grounding]`` HumanMessage injected.

        Pure function: does NOT mutate ``request`` or the state.
        Fails open: returns original request if any error occurs.
        """
        try:
            state = self._get_state_fn()
        except Exception as exc:
            logger.error(
                "booking_grounding.error",
                extra={
                    "booking_grounding.exception": str(exc),
                    "booking_grounding.phase": "get_state_fn",
                },
                exc_info=True,
            )
            return request

        # Mode guard
        if state.get("current_mode") != self._mode_name:
            return request

        try:
            directive = compute_next_prompt(state)
        except Exception as exc:
            logger.error(
                "booking_grounding.error",
                extra={
                    "booking_grounding.exception": str(exc),
                    "booking_grounding.phase": "compute_next_prompt",
                    "booking_grounding.mode": state.get("current_mode"),
                },
                exc_info=True,
            )
            return request

        # Build message content from directive
        lines = [
            _GROUNDING_PREFIX,
            f"action={directive.action}",
            directive.directive,
        ]
        if directive.mandatory_next_call:
            lines.append(f"NEXT_TOOL_REQUIRED={directive.mandatory_next_call}")
        if directive.context:
            import json
            try:
                ctx_str = json.dumps(directive.context, ensure_ascii=False, default=str)
                lines.append(f"context={ctx_str}")
            except Exception:
                pass  # context rendering is best-effort
        content = "\n".join(lines)

        new_msg = HumanMessage(content=content)
        msgs = list(request.messages)
        dedup = False

        # Dedup: scan from tail, replace last [grounding] if present
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if (
                isinstance(m, HumanMessage)
                and isinstance(m.content, str)
                and m.content.startswith(_GROUNDING_PREFIX)
            ):
                msgs[i] = new_msg
                dedup = True
                break

        if not dedup:
            msgs.append(new_msg)

        state_keys = list((state.get("booking_context") or {}).keys())
        logger.debug(
            "booking_grounding.injected",
            extra={
                "booking_grounding.action": directive.action,
                "booking_grounding.next_action": directive.mandatory_next_call,
                "booking_grounding.mandatory_next_call": directive.mandatory_next_call,
                "booking_grounding.state_snapshot_keys": state_keys,
                "booking_grounding.dedup": dedup,
            },
        )

        return request.override(messages=msgs)

    # ── AgentMiddleware interface ────────────────────────────────────────────

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Sync parity — required by AgentMiddleware parity contract (REQ-2)."""
        return handler(self._inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async path — primary entry point under ``create_agent.ainvoke``."""
        return await handler(self._inject(request))


__all__ = ["BookingGroundingMiddleware"]
