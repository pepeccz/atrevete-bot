"""AgentState TypedDict, BookingContext, and reducers for MVP v7."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, TypedDict
from uuid import UUID

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def replace_dict(current: dict | None, update: dict | None) -> dict | None:
    """Full-replace reducer for the booking slice.

    - (None, None)    → None
    - (current, None) → current   (no-op)
    - (current, update) → update  (full replace, NO merge)
    """
    if update is None:
        return current
    return update


AudienceTag = Literal["adult_female", "adult_male", "child_female", "child_male", "unisex", "baby"]


class BookingContext(TypedDict, total=False):
    service_ids: list[UUID]
    audience: AudienceTag | None
    stylist_id: UUID | None
    no_preference: bool
    date: date | None
    offered_slots: list[dict] | None
    selected_slot: dict | None
    customer_full_name: str | None
    notes: str | None
    step: Literal[
        "service",
        "audience",
        "more_services",
        "stylist",
        "date",
        "slot",
        "name",
        "notes",
        "confirm",
        "done",
    ]
    _escape_intent: (
        Literal["cancel", "start_over", "change_date", "change_service", "change_stylist"] | None
    )
    _notes_asked: bool


class AgentState(TypedDict):
    conversation_id: str
    customer_phone: str
    user_message: str
    pending_whatsapp_name: str | None
    current_mode: Literal["GENERAL", "BOOKING"]
    messages: Annotated[list[AnyMessage], add_messages]
    booking: Annotated[BookingContext | None, replace_dict]
    customer_id: UUID | None
    customer_name: str | None
