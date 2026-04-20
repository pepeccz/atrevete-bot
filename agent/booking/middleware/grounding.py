"""BookingGroundingMiddleware — injects a fresh ``[grounding]`` HumanMessage before each LLM call.

Calls ``compute_next_prompt(state)`` (pure function in ``agent/booking/grounding.py``) with the
current conversation state and injects the resulting GroundingInstruction as a message
whose content starts with ``[grounding]``.

Dedup algorithm (R4):
  - Scans messages from the tail looking for the last message whose content starts
    with ``"[grounding]"``.
  - If found, REPLACES it in-place (prevents accretion across loop iterations).
  - If not found, APPENDS the new message at the tail.

Mode guard (design §5.1):
  - If ``state.get("current_mode") != mode_name``, the message list passes through unchanged.
  - Allows safe inclusion in other mode stacks without behavioral impact.

Error handling (design §5.1 — fail-open):
  - Any exception in ``compute_next_prompt`` or ``get_state_fn`` is caught, logged as
    ``booking_grounding.error``, and the message list passes through unchanged.

Observability (design §9):
  - Emits ``booking_grounding.injected`` with fields:
    action, next_action (mandatory_next_call), state_snapshot_keys, dedup.
  - Emits ``booking_grounding.error`` with exception details on failure.

Design refs: design §5.1, §9
Requirements: R4, R5
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage

from agent.booking.grounding import compute_next_prompt

logger = logging.getLogger(__name__)

_GROUNDING_PREFIX = "[grounding]"


class BookingGroundingMiddleware:
    """Inject a fresh ``[grounding]`` HumanMessage before each LLM model call.

    Args:
        get_state_fn: Zero-arg callable that returns the current ConversationState dict.
            Called on EVERY model call so it always reflects the latest state
            (mid-loop tool mutations included).
        mode_name: The mode this middleware is active for (e.g. ``"BOOKING"``).
            If ``state["current_mode"] != mode_name``, the message list is passed through
            unchanged (design §5.1 mode-guard isolation).
    """

    def __init__(
        self,
        get_state_fn: Any,
        mode_name: str = "BOOKING",
    ) -> None:
        self._get_state_fn = get_state_fn
        self._mode_name = mode_name

    # ── Core injection logic ────────────────────────────────────────────────

    def _inject(self, messages: list, state: dict) -> list:
        """Return a new message list with the ``[grounding]`` HumanMessage injected.

        Does NOT mutate ``messages`` or ``state``.
        Fails open: returns original messages if any error occurs.

        Args:
            messages: Current message list.
            state: ConversationState dict (used for mode guard and compute_next_prompt).

        Returns:
            New message list with grounding injected (or original on failure/mode-guard).
        """
        # Mode guard — pass through if not BOOKING mode
        if state.get("current_mode") != self._mode_name:
            return messages

        try:
            directive = compute_next_prompt(state)
        except Exception as exc:
            _conv_id = state.get("conversation_id")
            _turn = state.get("total_message_count", 0)
            logger.error(
                "booking_grounding.error",
                extra={
                    "booking_grounding.exception": str(exc),
                    "booking_grounding.phase": "compute_next_prompt",
                    "booking_grounding.mode": state.get("current_mode"),
                    "booking_grounding.conversation_id": _conv_id,
                    "booking_grounding.turn": _turn,
                },
                exc_info=True,
            )
            return messages

        # Build message content from directive
        # NOTE: GroundingInstruction uses .reason (not .directive) and .data (not .context)
        lines = [
            _GROUNDING_PREFIX,
            f"action={directive.action}",
            directive.reason,
        ]
        if directive.mandatory_next_call:
            lines.append(f"NEXT_TOOL_REQUIRED={directive.mandatory_next_call}")
        if directive.data:
            import json
            try:
                ctx_str = json.dumps(directive.data, ensure_ascii=False, default=str)
                lines.append(f"context={ctx_str}")
            except Exception:
                pass  # context rendering is best-effort
        content = "\n".join(lines)

        new_msg = HumanMessage(content=content)
        msgs = list(messages)
        dedup = False

        # Dedup: scan from tail, replace last [grounding] if present
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if (
                hasattr(m, "content")
                and isinstance(m.content, str)
                and m.content.startswith(_GROUNDING_PREFIX)
            ):
                msgs[i] = new_msg
                dedup = True
                break

        if not dedup:
            msgs.append(new_msg)

        _conv_id = state.get("conversation_id")
        _turn = state.get("total_message_count", 0)
        state_keys = list((state.get("booking_context") or {}).keys())

        logger.debug(
            "booking_grounding.injected",
            extra={
                "booking_grounding.conversation_id": _conv_id,
                "booking_grounding.turn": _turn,
                "booking_grounding.action": directive.action,
                "booking_grounding.next_action": directive.mandatory_next_call,
                "booking_grounding.mandatory_next_call": directive.mandatory_next_call,
                "booking_grounding.state_snapshot_keys": state_keys,
                "booking_grounding.dedup": dedup,
            },
        )

        return msgs

    # ── AgentMiddleware-compatible interface ────────────────────────────────

    def before_model(self, messages: list, state: dict) -> list:
        """Alias for _inject — hook called before each LLM invocation."""
        return self._inject(messages, state)


__all__ = ["BookingGroundingMiddleware"]
