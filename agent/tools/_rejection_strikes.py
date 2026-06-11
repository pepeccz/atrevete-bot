"""Consecutive-rejection strike layer (Change N / N3, V6 audit C3).

When the SAME tool gets rejected with the SAME next_step twice consecutively,
the rejection payload escalates from a plain error message to a directive
instructing the LLM to call `escalate` — a deterministic exit for the
fabricate → reject → re-offer → fabricate dead loops observed in QA V6.

The counter is derived from the checkpointed message history (ToolMessages),
which is reducer-safe by construction (`add_messages` is append-only): no
extra state write path is needed and the count survives across turns.

Consumers: agent/tools/book.py, agent/tools/update_booking.py.
"""

from __future__ import annotations

import json
import logging

from agent.tools.schemas import ToolResponse

logger = logging.getLogger(__name__)

REJECTION_ESCALATION_THRESHOLD = 2
"""Strike count (current rejection included) at which the directive fires."""

_STRIKE_EXEMPT_NEXT_STEPS: frozenset[str] = frozenset(
    {
        # Recoverable normal-flow gates — these are expected in a healthy booking flow and
        # resolve themselves when the LLM calls check_availability or gets confirmation.
        # Counting them toward escalation threshold causes premature escalation (O4 V7 fix).
        "reoffer_slots",
        "confirmation_required",
        "pre_book_validation_required",
        # Policy gate has its own deterministic escalation path (R36) — exempt as before.
        "policy_acceptance_required",
    }
)
"""next_step values exempt from the forced-escalation strike counter.

Normal-flow gates (reoffer_slots, confirmation_required, pre_book_validation_required)
are recoverable and expected in multi-turn booking flows. Only true validator refusals
(invalid_service_ids, invalid_stylist_id, slot_not_offered after a genuine re-offer,
policy/ownership failures) should count toward the escalation threshold.
"""


def count_consecutive_rejections(messages: list, tool_name: str, next_step: str) -> int:
    """Count trailing consecutive rejections of tool_name with the given next_step.

    Scans the message history backwards considering only ToolMessages emitted
    by `tool_name`. Counting stops at the first response of that tool that is
    NOT an identical rejection (success resets the streak). Messages from
    other tools, AI or human messages never reset the streak.

    Args:
        messages:  LangChain message list from state (may be empty/None).
        tool_name: Tool whose rejections are being counted (e.g. "book").
        next_step: Rejection next_step to match (strikes are keyed per reason).

    Returns:
        Number of trailing consecutive identical rejections (0 when none).
    """
    count = 0
    for msg in reversed(messages or []):
        if getattr(msg, "name", None) != tool_name:
            continue
        content = getattr(msg, "content", None)
        if not isinstance(content, str):
            break
        try:
            data = json.loads(content)
        except (ValueError, TypeError):
            break
        if not isinstance(data, dict):
            break
        if data.get("status") == "rejected" and data.get("next_step") == next_step:
            count += 1
        else:
            break
    return count


def apply_rejection_strike(response: ToolResponse, messages: list, tool_name: str) -> ToolResponse:
    """Transform a rejection into an escalation directive at the strike threshold.

    Pass-through for non-rejected responses, rejections without next_step,
    and next_steps with their own escalation path (policy gate). Otherwise,
    when the current rejection is the REJECTION_ESCALATION_THRESHOLD-th
    consecutive identical rejection of this tool, return a new ToolResponse
    with next_step="escalation_required" carrying the validator reason.

    Args:
        response:  The ToolResponse the tool is about to return.
        messages:  Message history from injected state (prior ToolMessages).
        tool_name: Name of the calling tool ("book" | "update_booking").

    Returns:
        The original response, or the escalation directive at 2 strikes.
    """
    if response.status != "rejected" or not response.next_step:
        return response
    if response.next_step in _STRIKE_EXEMPT_NEXT_STEPS:
        return response

    prior = count_consecutive_rejections(messages, tool_name, response.next_step)
    strikes = prior + 1
    if strikes < REJECTION_ESCALATION_THRESHOLD:
        return response

    reason = "; ".join(response.errors) if response.errors else response.next_step
    logger.warning(
        "tool.rejection.escalation_directive tool_name=%s original_next_step=%s strikes=%d",
        tool_name,
        response.next_step,
        strikes,
        extra={
            "tool_name": tool_name,
            "original_next_step": response.next_step,
            "consecutive_rejections": strikes,
        },
    )
    return ToolResponse(
        status="rejected",
        next_step="escalation_required",
        payload={
            **response.payload,
            "original_next_step": response.next_step,
            "rejection_reason": reason,
            "consecutive_rejections": strikes,
        },
        errors=[
            f"Esta operación ha fallado {strikes} veces seguidas con el mismo motivo: "
            f"{reason} "
            "No reintentes la misma llamada ni pidas permiso al cliente para reintentar. "
            "Llama AHORA a escalate(reason='technical_error') y discúlpate brevemente "
            "con el cliente."
        ],
    )


def apply_rejection_strike_json(raw_json: str, messages: list, tool_name: str) -> str:
    """JSON-string variant for tools whose impl returns a serialized ToolResponse.

    Parses raw_json; when it is a rejection at the strike threshold, returns the
    serialized escalation directive. Any parse failure returns raw_json as-is
    (fail-open: the strike layer must never break a tool response).
    """
    try:
        data = json.loads(raw_json)
        if not isinstance(data, dict) or data.get("status") != "rejected":
            return raw_json
        response = ToolResponse(**data)
    except Exception:
        # fail-open: malformed tool response JSON — return raw_json unchanged so the
        # tool-calling loop is never broken by a strike-layer parse failure
        return raw_json

    transformed = apply_rejection_strike(response, messages, tool_name)
    if transformed is response:
        return raw_json
    return transformed.model_dump_json()
