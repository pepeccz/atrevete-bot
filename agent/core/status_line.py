"""Pre-turn HumanMessage builder summarising current ConversationState.

Replacement strategy for the cached-stale ``<dynamic_context>`` XML block
(bug #3949). ``build_status_line`` produces a fresh-per-turn HumanMessage
rather than a SystemMessage so it bypasses the ``create_agent`` system-prompt
cache that caused stale state injection.

G8 reconciliation (from e1-scaffolding design):
  - ``state_delivery.py`` corrects past-turn anchoring by injecting synthetic
    AIMessage+ToolMessage pairs into history retrospectively.
  - ``status_line.py`` provides a current-state snapshot as a HumanMessage
    prepended before the NEXT LLM turn (prospective).
  They are complementary and MUST NOT be merged.

E1 introduces the builder; first wired caller is BookingCapability in E2.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from agent.state.schemas import ConversationState

MAX_CONTENT_CHARS = 600  # ≈150 tokens proxy per spec R12


def build_status_line(state: ConversationState) -> HumanMessage:
    """Return a deterministic HumanMessage summarising state for the next LLM turn.

    Pure function: no I/O, no randomness, does NOT mutate state.

    Output format::

        [estado] modo=<mode>; servicios=<csv-or-empty>; estilista=<name-or-empty>;
        slot=<HH:MM-or-empty>; cliente=<name-or-empty>; flags=<csv>

    Token budget of ``MAX_CONTENT_CHARS`` is enforced; content is hard-truncated
    with ellipsis if the assembled string exceeds the budget.
    """
    parts: list[str] = []
    parts.append(f"modo={_safe_str(state.get('current_mode'))}")

    bc: dict = state.get("booking_context") or {}
    parts.append(f"servicios={_csv(bc.get('last_services'))}")
    parts.append(f"estilista={_safe_str(bc.get('last_stylist'))}")

    selected: dict = bc.get("selected_slot") or {}
    parts.append(f"slot={_safe_str(selected.get('start_time'))}")
    parts.append(f"cliente={_safe_str(state.get('customer_first_name'))}")
    parts.append(f"flags={_flags_csv(bc)}")

    body = "[estado] " + "; ".join(parts)

    if len(body) > MAX_CONTENT_CHARS:
        body = body[: MAX_CONTENT_CHARS - 3] + "..."

    return HumanMessage(content=body)


# ── Private helpers ──────────────────────────────────────────────────────────


def _safe_str(v: object) -> str:
    """Return empty string for None, string representation otherwise."""
    return "" if v is None else str(v)


def _csv(v: object) -> str:
    """Return comma-joined string for a list, empty string otherwise."""
    if not v or not isinstance(v, list):
        return ""
    return ",".join(str(x) for x in v)


def _flags_csv(bc: dict) -> str:
    """Return alphabetically-sorted CSV of active boolean flags for determinism (R11)."""
    flags: list[str] = []
    if bc.get("_booking_completed"):
        flags.append("completed")
    if bc.get("_confirmation_shown"):
        flags.append("confirmation")
    if bc.get("notes_asked"):
        flags.append("notes_asked")
    if bc.get("add_more_asked"):
        flags.append("add_more_asked")
    return ",".join(sorted(flags))
