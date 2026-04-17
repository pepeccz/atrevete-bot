"""
Synthetic state-delivery helper — E1 capability-contract primitive.

Provides two pure functions that construct a synthetic (AIMessage + ToolMessage)
pair representing a fresh tool signal. Used to correct LLM anchoring mid-flow
without waiting for the next graph turn.

Pure contract:
- Does NOT mutate input dicts.
- Does NOT import from agent/modes/ or agent/tools/ (no cycles).
- Only imports: langchain_core, stdlib, shared.config.

Usage::

    from agent.core import deliver_state_update

    synthetic_msgs = deliver_state_update(
        tool_name="update_booking",
        tool_args={"services": ["Corte Señora"]},
        build_response_fn=booking_data_tools._build_response,
        booking_context=booking_context,
        context_label="audience-t3",
        conversation_id=state.get("conversation_id"),
    )
    # Append synthetic_msgs to transcript and to updates["messages"].
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Callable, Final

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from shared.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

SYNTHETIC_TOOL_CALL_ID_PREFIX: Final[str] = "synth-"

# Type alias for the build_response_fn callable.
# Shape: (ctx: dict, success: bool = True, validation_errors: list | None = None) -> dict
BuildResponseFn = Callable[..., dict[str, Any]]


# ---------------------------------------------------------------------------
# build_synthetic_state_delivery
# ---------------------------------------------------------------------------


def build_synthetic_state_delivery(
    tool_name: str,
    tool_args: dict[str, Any],
    tool_response: dict[str, Any] | str,
    tool_call_id: str | None = None,
) -> list[BaseMessage]:
    """Build a synthetic (AIMessage(tool_calls=[…]) + ToolMessage) pair.

    Pure — does not touch external state. Returns exactly ``[ai_msg, tool_msg]``
    ready to append to a message list or LangGraph state.

    Args:
        tool_name: Name of the tool being synthesised (e.g. ``"update_booking"``).
        tool_args: Arguments dict for the synthetic tool call.
        tool_response: Content for the ToolMessage — serialised to JSON if dict.
        tool_call_id: Explicit ID. Auto-generated (``synth-<hash>``) if None.

    Returns:
        ``[AIMessage, ToolMessage]`` with matching ``tool_call_id`` values.
    """
    if tool_call_id is None:
        # Generate a unique ID in the form synth-<8hex> for anonymous calls.
        tool_call_id = f"{SYNTHETIC_TOOL_CALL_ID_PREFIX}{uuid.uuid4().hex[:12]}"

    # Serialise response to JSON string if needed.
    if isinstance(tool_response, dict):
        tool_content = json.dumps(tool_response, ensure_ascii=False)
    else:
        tool_content = str(tool_response)

    ai_msg = AIMessage(
        content="",  # Empty → invisible to renderer (V4 verification).
        tool_calls=[
            {
                "name": tool_name,
                "args": dict(tool_args),  # shallow copy to avoid aliasing
                "id": tool_call_id,
                "type": "tool_call",
            }
        ],
    )
    tool_msg = ToolMessage(
        content=tool_content,
        tool_call_id=tool_call_id,
        name=tool_name,
    )
    return [ai_msg, tool_msg]


# ---------------------------------------------------------------------------
# deliver_state_update
# ---------------------------------------------------------------------------


def deliver_state_update(
    tool_name: str,
    tool_args: dict[str, Any],
    build_response_fn: BuildResponseFn,
    booking_context: dict[str, Any],
    context_label: str | None = None,
    conversation_id: str | None = None,
) -> list[BaseMessage]:
    """Synthesise a state-delivery message pair representing a fresh tool signal.

    Steps:
    1. Check feature flag — return [] unconditionally if disabled.
    2. Invoke ``build_response_fn(booking_context, success=True, validation_errors=None)``
       to compute the synthetic ToolMessage content.
    3. Wrap via ``build_synthetic_state_delivery``.
    4. Emit ``booking.synthetic_state_delivery`` telemetry at INFO level.
    5. On any exception or invalid return → return [] + log warning.

    Purity invariant: ``booking_context`` is NEVER modified.

    Args:
        tool_name: Tool name for the synthetic AIMessage tool_call.
        tool_args: Tool arguments for the synthetic tool_call.
        build_response_fn: Callable that computes the ToolMessage content.
            Signature: ``(ctx: dict, success: bool, validation_errors: list | None) -> dict``.
        booking_context: Current booking context snapshot (read-only).
        context_label: Short label for telemetry and ID suffix (e.g. ``"audience-t3"``).
        conversation_id: Conversation ID for telemetry (unhashed, may be None).

    Returns:
        ``[AIMessage, ToolMessage]`` on success, ``[]`` on any error or disabled flag.
    """
    settings = get_settings()

    # Feature flag gate (R4, S5).
    if not settings.state_delivery_synthetic_enabled:
        _emit_telemetry(
            tool_name=tool_name,
            tool_call_id=None,
            delivered=False,
            context_label=context_label,
            conversation_id=conversation_id,
            reason="feature_flag_disabled",
        )
        return []

    # Build a unique tool_call_id embedding the context_label.
    label_part = context_label or "synthetic"
    random_suffix = hashlib.sha256(
        f"{conversation_id}:{tool_name}:{label_part}:{uuid.uuid4().hex[:8]}".encode()
    ).hexdigest()[:12]
    tool_call_id = f"{SYNTHETIC_TOOL_CALL_ID_PREFIX}{label_part}-{random_suffix}"

    # Invoke response builder — pure read of booking_context, no mutation.
    try:
        tool_response = build_response_fn(booking_context, True, None)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "deliver_state_update: build_response_fn raised — skipping delivery",
            extra={"error": str(exc), "tool_name": tool_name, "context_label": context_label},
        )
        _emit_telemetry(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            delivered=False,
            context_label=context_label,
            conversation_id=conversation_id,
            reason="build_response_error",
        )
        return []

    if not isinstance(tool_response, dict):
        logger.warning(
            "deliver_state_update: build_response_fn returned non-dict — skipping delivery",
            extra={
                "tool_name": tool_name,
                "context_label": context_label,
                "got_type": type(tool_response).__name__,
            },
        )
        _emit_telemetry(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            delivered=False,
            context_label=context_label,
            conversation_id=conversation_id,
            reason="build_response_error",
        )
        return []

    msgs = build_synthetic_state_delivery(
        tool_name=tool_name,
        tool_args=tool_args,
        tool_response=tool_response,
        tool_call_id=tool_call_id,
    )

    _emit_telemetry(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        delivered=True,
        context_label=context_label,
        conversation_id=conversation_id,
        reason=None,
        tool_args_keys=list(tool_args.keys()),
    )
    return msgs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _emit_telemetry(
    *,
    tool_name: str,
    tool_call_id: str | None,
    delivered: bool,
    context_label: str | None,
    conversation_id: str | None,
    reason: str | None,
    tool_args_keys: list[str] | None = None,
) -> None:
    """Emit booking.synthetic_state_delivery structured log (R5, S7)."""
    logger.info(
        "booking.synthetic_state_delivery",
        extra={
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "delivered": delivered,
            "context_label": context_label,
            "reason_if_not_delivered": reason,
            "tool_args_keys": tool_args_keys or [],
        },
    )
