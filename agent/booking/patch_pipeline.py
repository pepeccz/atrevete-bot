"""
Booking patch pipeline — resolver result types and apply-patch helper.

Design ref: design §2.2 Q6, spec R2.6–R2.8, tasks B.2.4

The patch_pipeline module provides:
  - ResolverResult TypedDict: metadata-rich result from any pre-loop resolver.
  - apply_resolver_patch: single mutation channel for all pre-loop state changes.
  - resolve_add_more_negation: wrapper for is_negation → ResolverResult.

All pure-resolver functions in infra/resolvers/ retain their current signatures.
Wrappers here convert raw resolver output into ResolverResult dicts and apply them
to booking_context in a single, telemetry-emitting operation.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ResolverResult TypedDict
# ---------------------------------------------------------------------------


class ResolverResult(TypedDict, total=False):
    """Metadata-rich result from a pre-loop booking resolver.

    Fields:
        source: Identifier string for the resolver that produced this result
                (e.g. "is_negation", "is_affirmation", "resolve_stylist").
        matched: True if the resolver matched and produced a patch.
        patch: Dict of key→value updates to apply to booking_context.
        reason: Human-readable explanation of the match (for telemetry).
    """

    source: str
    matched: bool
    patch: dict[str, Any]
    reason: str


# ---------------------------------------------------------------------------
# apply_resolver_patch — single mutation channel
# ---------------------------------------------------------------------------


def apply_resolver_patch(
    booking_context: dict[str, Any],
    result: ResolverResult | None,
    *,
    conversation_id: str = "",
    turn: int = 0,
) -> dict[str, Any]:
    """Apply a resolver patch to booking_context in-place and emit telemetry.

    This is the single authorized mutation channel for pre-loop resolver patches.
    All direct booking_context[k]=v assignments in handle() must flow through here.

    Args:
        booking_context: The current booking context dict (mutated in-place).
        result: A ResolverResult from a resolver wrapper, or None.
        conversation_id: For telemetry logging.
        turn: Current turn number for telemetry logging.

    Returns:
        booking_context (same object, mutated in-place) — allows chaining.

    Behavior:
        - If result is None or matched=False, no-op.
        - Otherwise applies all keys in result["patch"] to booking_context.
        - Emits structured log event resolver.<source>.applied.
    """
    if not result or not result.get("matched"):
        return booking_context

    patch = result.get("patch") or {}
    if not patch:
        return booking_context

    for key, value in patch.items():
        booking_context[key] = value

    logger.info(
        "resolver.%s.applied | conv_id=%s | turn=%s | patch_keys=%s | reason=%s",
        result.get("source", "unknown"),
        conversation_id,
        turn,
        list(patch.keys()),
        result.get("reason", ""),
    )

    return booking_context


# ---------------------------------------------------------------------------
# resolve_add_more_negation — wrapper for is_negation (B.2.4)
# ---------------------------------------------------------------------------


def resolve_add_more_negation(
    user_text: str,
    state: dict[str, Any],
    bc: dict[str, Any],
) -> ResolverResult | None:
    """Resolve whether user's message is a negation of '¿algo más?'.

    This is the sole writer for add_more_asked=True in the pre-loop phase.

    Guards:
    - bc.get("add_more_asked") is already True → return None (idempotent).
    - compute_next_prompt(state).action != "ASK_MORE_SERVICES" → return None
      (only fires when the grounding action requires an answer to 'algo más?').

    Args:
        user_text: Raw user message text.
        state: Full ConversationState dict.
        bc: Current booking_context dict.

    Returns:
        ResolverResult with matched=True and patch={"add_more_asked": True},
        or None if the guard conditions are not met.
    """
    # Guard 1: already set — idempotent
    if bc.get("add_more_asked"):
        return None

    # Guard 2: only fire when grounding action is ASK_MORE_SERVICES
    try:
        from agent.booking.grounding import compute_next_prompt

        directive = compute_next_prompt(state)
        if directive.action != "ASK_MORE_SERVICES":
            return None
    except Exception:
        # Fail open: if compute_next_prompt raises, don't block the turn
        return None

    # Check if user's message is a negation
    from infra.resolvers.negation import is_negation

    matched, canonical, distance = is_negation(user_text)
    if not matched:
        return None

    reason = f"matched={canonical!r}"
    if distance >= 0:
        reason += f" distance={distance}"

    return {
        "source": "is_negation",
        "matched": True,
        "patch": {"add_more_asked": True},
        "reason": reason,
    }
