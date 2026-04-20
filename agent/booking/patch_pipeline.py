"""
Booking patch pipeline — resolver result types and apply-patch helper.

Design ref: design §2.2 Q6, spec R2.6–R2.8, tasks B.2.4, B.3.5

The patch_pipeline module provides:
  - ResolverResult TypedDict: metadata-rich result from any pre-loop resolver.
  - apply_resolver_patch: single mutation channel for all pre-loop state changes.
  - resolve_add_more_negation: wrapper for is_negation → ResolverResult (B.2).
  - resolve_confirmation: wrapper for is_affirmation/is_negation on confirmed (B.3).
  - resolve_stylist_selection: wrapper for resolve_stylist (B.3).
  - resolve_digit_selection: wrapper for digit→slot logic (B.3).
  - resolve_customer_from_state: wrapper for customer suggestion pre-fill (B.3).
  - resolve_service_category: guard-only wrapper (returns None; category set via async) (B.3).

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


# ---------------------------------------------------------------------------
# resolve_confirmation — wrapper for is_affirmation / is_negation (B.3.5)
# ---------------------------------------------------------------------------


def resolve_confirmation(
    user_text: str,
    bc: dict[str, Any],
) -> ResolverResult | None:
    """Resolve confirmation/rejection of the booking summary.

    Guards:
    - _confirmation_shown must be True (summary was shown).
    - confirmed must not already be set (idempotent).

    Returns ResolverResult with patch={"confirmed": True|False} or None.
    """
    if not bc.get("_confirmation_shown"):
        return None
    if bc.get("confirmed") is not None:
        return None

    from infra.resolvers.affirmation import is_affirmation
    from infra.resolvers.negation import is_negation

    if is_affirmation(user_text):
        return {
            "source": "is_affirmation",
            "matched": True,
            "patch": {"confirmed": True},
            "reason": "affirmation matched",
        }

    matched, canonical, distance = is_negation(user_text)
    if matched:
        reason = f"negation matched={canonical!r}"
        if distance >= 0:
            reason += f" distance={distance}"
        return {
            "source": "is_negation",
            "matched": True,
            "patch": {"confirmed": False, "_confirmation_shown": False},
            "reason": reason,
        }

    return None


# ---------------------------------------------------------------------------
# resolve_stylist_selection — wrapper for resolve_stylist (B.3.5)
# ---------------------------------------------------------------------------


def resolve_stylist_selection(
    user_text: str,
    offered_stylists: list[str],
    bc: dict[str, Any],
    *,
    conversation_id: str = "",
    turn: int = 0,
) -> ResolverResult | None:
    """Resolve stylist selection from user message.

    Returns ResolverResult with patch keys from resolve_stylist, or None.
    Does not fire if last_stylist already set.
    """
    if not offered_stylists:
        return None
    if bc.get("last_stylist") or bc.get("no_preference_stylist"):
        return None

    from infra.resolvers.stylist import resolve_stylist

    patch = resolve_stylist(
        user_text,
        offered_stylists,
        conversation_id=conversation_id,
        turn_number=turn,
    )
    if patch is None:
        return None

    return {
        "source": "resolve_stylist",
        "matched": True,
        "patch": patch,
        "reason": f"stylist resolved from {user_text!r:.40}",
    }


# ---------------------------------------------------------------------------
# resolve_digit_selection — wrapper for digit→slot fast-path (B.3.5)
# ---------------------------------------------------------------------------


def resolve_digit_selection(
    user_text: str,
    bc: dict[str, Any],
) -> ResolverResult | None:
    """Resolve bare digit input to a selected_slot.

    Returns ResolverResult with patch={"selected_slot": ..., "last_stylist": ...}
    when the user sends a single digit matching an offered slot.
    Returns None otherwise (including when selected_slot already set).
    """
    offered_slots: list[dict[str, Any]] = bc.get("offered_slots") or []
    if not offered_slots or bc.get("selected_slot"):
        return None

    try:
        digit = int(user_text.strip())
    except (ValueError, TypeError):
        return None

    if not (1 <= digit <= len(offered_slots)):
        return None

    slot = offered_slots[digit - 1]
    patch: dict[str, Any] = {"selected_slot": slot}
    if not bc.get("last_stylist") and slot.get("stylist_name"):
        patch["last_stylist"] = slot["stylist_name"]

    return {
        "source": "resolve_digit",
        "matched": True,
        "patch": patch,
        "reason": f"digit {digit} → slot {slot.get('start_time', '?')!r}",
    }


# ---------------------------------------------------------------------------
# resolve_customer_from_state — informational pre-fill wrapper (B.3.5)
# ---------------------------------------------------------------------------


def resolve_customer_from_state(
    state: dict[str, Any],
    bc: dict[str, Any],
) -> ResolverResult | None:
    """Inject customer suggestion from state if not already in booking context.

    Informational pre-fill per spec R3.2 exception:
    - _suggested_customer_name and customer_id are allowed pre-fills.
    - Does NOT set customer_name (requires explicit user confirmation).

    Returns ResolverResult or None if nothing to fill.
    """
    # Already have suggestion AND id — nothing to do
    if bc.get("customer_name") and bc.get("_suggested_customer_name"):
        return None

    patch: dict[str, Any] = {}

    if not bc.get("customer_name") and not bc.get("_suggested_customer_name"):
        state_name = state.get("customer_first_name") or state.get("customer_name")
        if state_name:
            patch["_suggested_customer_name"] = str(state_name)

    if not bc.get("customer_id"):
        state_id = state.get("customer_id")
        if state_id:
            patch["customer_id"] = str(state_id)

    if not patch:
        return None

    return {
        "source": "customer_from_state",
        "matched": True,
        "patch": patch,
        "reason": "customer pre-fill from state",
    }


# ---------------------------------------------------------------------------
# resolve_service_category — guard-only wrapper (B.3.5)
# ---------------------------------------------------------------------------


def resolve_service_category(
    bc: dict[str, Any],
) -> ResolverResult | None:
    """Guard-only wrapper: returns None always.

    The actual DB lookup in _resolve_service_category is async and sets
    booking_context["last_service_category"] directly (permitted as an
    async infrastructure call). This wrapper exists to satisfy the
    resolver format contract tests without changing the async pattern.

    Returns None when:
    - No last_services (nothing to look up)
    - last_service_category already cached

    Always returns None (category is set via async DB call, not patch pipeline).
    """
    if not bc.get("last_services"):
        return None
    if bc.get("last_service_category"):
        return None
    # Category lookup is async; cannot be done here.
    # Caller (_resolve_service_category static method) performs the DB call.
    return None
