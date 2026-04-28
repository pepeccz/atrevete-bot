"""AgentState TypedDict — slim schema for create_agent MVP rewrite."""

from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict, get_type_hints
from uuid import UUID

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

# ---------------------------------------------------------------------------
# Slot registry (SSOT) — T6
# Order matches PromptAssemblyMiddleware slot injection order.
# ---------------------------------------------------------------------------
SLOT_REGISTRY: tuple[str, ...] = (
    "_slot_today",
    "_slot_customer",
    "_slot_upcoming_appointments",
    "_slot_business_hours",
    "_slot_availability",
    "_slot_catalog",
)


class AgentState(TypedDict):
    conversation_id: str
    customer_phone: str
    user_message: str | None
    pending_whatsapp_name: str | None
    messages: Annotated[list[AnyMessage], add_messages]
    customer_id: UUID | None
    customer_name: str | None
    # T3 — normalize to NotRequired (matches last_summarized_msg_count pattern)
    conversation_summary: NotRequired[str | None]
    last_summarized_msg_count: NotRequired[int | None]
    # T7 — 6 slot fields, NotRequired[str] (absence encodes "not set")
    _slot_today: NotRequired[str]
    _slot_customer: NotRequired[str]
    _slot_upcoming_appointments: NotRequired[str]
    _slot_business_hours: NotRequired[str]
    _slot_availability: NotRequired[str]
    _slot_catalog: NotRequired[str]


# ---------------------------------------------------------------------------
# Boot-time drift guard — T9
# Raises RuntimeError (survives python -O) if SLOT_REGISTRY and the _slot_*
# fields declared in AgentState fall out of sync.
# ---------------------------------------------------------------------------

def _validate_registry() -> None:
    """Compare SLOT_REGISTRY against AgentState._slot_* declarations.

    Raises RuntimeError with message containing "SLOT_REGISTRY drift" if any
    key is present in one set but missing from the other.
    """
    hints = get_type_hints(AgentState, include_extras=True)
    declared = {k for k in hints if k.startswith("_slot_")}
    registered = set(SLOT_REGISTRY)
    if declared != registered:
        only_declared = declared - registered
        only_registered = registered - declared
        raise RuntimeError(
            f"SLOT_REGISTRY drift: declared-but-not-registered={only_declared}, "
            f"registered-but-not-declared={only_registered}"
        )


_validate_registry()
