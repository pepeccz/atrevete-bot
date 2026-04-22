"""LLM leaves for the booking subgraph — Phase 5.8 + booking-prompts-audit-fix.

Each leaf:
1. Checks fast-path: if the required field is already set in booking, skip LLM
   and return Command(goto="route_next") to advance to the next step.
2. Otherwise: calls build_leaf_system_message to build a SystemMessage, then
   calls LLM.with_structured_output(Schema).ainvoke([SystemMessage, ...messages]).
3. Merges extracted fields into booking sub-dict.
4. Returns Command(goto=END, update={messages:[AIMessage(...)], booking:{...}})
   to end the subgraph turn (waiting for next user message).
   Exception: fetch_availability and execute_book chain further since they
   don't require user input (see actions.py).

Fast-path behavior (field already set):
  - Returns Command(goto="route_next") which advances the booking step.
  - No message emitted (already handled earlier).

get_llm is imported at call time so tests can patch it at agent.booking.leaves.get_llm.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.constants import END
from langgraph.types import Command

from agent.booking.prompt_builder import build_leaf_system_message
from agent.booking.schemas import (
    AudienceResponse,
    DateResponse,
    MoreServicesResponse,
    NameResponse,
    NotesResponse,
    ServiceSelectionResponse,
    SlotResponse,
    StylistResponse,
)

logger = logging.getLogger(__name__)


def get_llm():
    """Return default LLM. Patchable in tests."""
    from agent.llm import get_llm as _factory

    return _factory()


def _current_messages(state: dict[str, Any]) -> list:
    return state.get("messages") or []


async def ask_service(state: dict[str, Any]) -> Command:
    """Ask user which service they want."""
    import agent.booking.leaves as _self

    booking = dict(state.get("booking") or {})

    # Fast-path: service_ids already resolved → advance step
    if booking.get("service_ids"):
        if not booking.get("step") or booking.get("step") == "service":
            booking["step"] = "audience"
        return Command(goto="route_next", update={"booking": booking})

    system_msg = await build_leaf_system_message("ask_service", booking, state)
    llm = _self.get_llm()
    chain = llm.with_structured_output(ServiceSelectionResponse)
    messages = [system_msg] + _current_messages(state)
    response: ServiceSelectionResponse = await chain.ainvoke(messages)

    booking.update(
        {
            "service_ids": response.selected_service_ids or [],
        }
    )

    if booking["service_ids"]:
        booking["step"] = "audience"
        return Command(goto="route_next", update={"booking": booking})

    booking["step"] = "service"
    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=response.message)],
            "booking": booking,
        },
    )


async def ask_audience(state: dict[str, Any]) -> Command:
    """Ask user for the target audience."""
    import agent.booking.leaves as _self

    booking = dict(state.get("booking") or {})

    if booking.get("audience"):
        booking["step"] = "stylist"
        return Command(goto="route_next", update={"booking": booking})

    system_msg = await build_leaf_system_message("ask_audience", booking, state)
    llm = _self.get_llm()
    chain = llm.with_structured_output(AudienceResponse)
    messages = [system_msg] + _current_messages(state)
    response: AudienceResponse = await chain.ainvoke(messages)

    booking["audience"] = response.inferred_audience
    if response.inferred_audience:
        booking["step"] = "more_services"
        return Command(goto="route_next", update={"booking": booking})

    booking["step"] = "audience"
    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=response.message)],
            "booking": booking,
        },
    )


async def ask_more_services(state: dict[str, Any]) -> Command:
    """Ask user if they want to add more services."""
    import agent.booking.leaves as _self

    booking = dict(state.get("booking") or {})

    # Fast-path: already asked and user declined — advance
    if booking.get("_more_services_asked"):
        booking["step"] = "stylist"
        return Command(goto="route_next", update={"booking": booking})

    system_msg = await build_leaf_system_message("ask_more_services", booking, state)
    llm = _self.get_llm()
    chain = llm.with_structured_output(MoreServicesResponse)
    messages = [system_msg] + _current_messages(state)
    response: MoreServicesResponse = await chain.ainvoke(messages)

    if response.additional_service_ids:
        existing = list(booking.get("service_ids") or [])
        for sid in response.additional_service_ids:
            if sid not in existing:
                existing.append(sid)
        booking["service_ids"] = existing

    if response.user_declined:
        booking["_more_services_asked"] = True
        booking["step"] = "stylist"
        return Command(goto="route_next", update={"booking": booking})

    # Added services but not declined — ask again next turn
    booking["step"] = "more_services"
    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=response.message)],
            "booking": booking,
        },
    )


async def ask_stylist(state: dict[str, Any]) -> Command:
    """Ask user for stylist preference."""
    import agent.booking.leaves as _self

    booking = dict(state.get("booking") or {})

    if booking.get("stylist_id") or booking.get("no_preference"):
        booking["step"] = "date"
        return Command(goto="route_next", update={"booking": booking})

    system_msg = await build_leaf_system_message("ask_stylist", booking, state)
    llm = _self.get_llm()
    chain = llm.with_structured_output(StylistResponse)
    messages = [system_msg] + _current_messages(state)
    response: StylistResponse = await chain.ainvoke(messages)

    booking["stylist_id"] = response.inferred_stylist_id
    booking["no_preference"] = response.no_preference

    if response.inferred_stylist_id or response.no_preference:
        booking["step"] = "date"
        return Command(goto="route_next", update={"booking": booking})

    booking["step"] = "stylist"
    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=response.message)],
            "booking": booking,
        },
    )


async def ask_date(state: dict[str, Any]) -> Command:
    """Ask user for the desired date."""
    import agent.booking.leaves as _self

    booking = dict(state.get("booking") or {})

    if booking.get("date"):
        booking["step"] = "slot"
        return Command(goto="route_next", update={"booking": booking})

    system_msg = await build_leaf_system_message("ask_date", booking, state)
    llm = _self.get_llm()
    chain = llm.with_structured_output(DateResponse)
    messages = [system_msg] + _current_messages(state)
    response: DateResponse = await chain.ainvoke(messages)

    booking["date"] = response.inferred_date
    if response.inferred_date:
        booking["step"] = "slot"
        return Command(goto="route_next", update={"booking": booking})

    booking["step"] = "date"
    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=response.message)],
            "booking": booking,
        },
    )


async def ask_slot(state: dict[str, Any]) -> Command:
    """Present available slots and ask user to pick one."""
    import agent.booking.leaves as _self

    booking = dict(state.get("booking") or {})

    if booking.get("selected_slot"):
        booking["step"] = "name"
        return Command(goto="route_next", update={"booking": booking})

    system_msg = await build_leaf_system_message("ask_slot", booking, state)
    llm = _self.get_llm()
    chain = llm.with_structured_output(SlotResponse)
    messages = [system_msg] + _current_messages(state)
    response: SlotResponse = await chain.ainvoke(messages)

    offered_slots = booking.get("offered_slots") or []
    idx = response.selected_slot_index
    if idx is not None and 0 <= idx < len(offered_slots):
        booking["selected_slot"] = offered_slots[idx]
        booking["step"] = "name"
        return Command(goto="route_next", update={"booking": booking})

    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=response.message)],
            "booking": booking,
        },
    )


async def ask_name(state: dict[str, Any]) -> Command:
    """Ask user for their name for the booking."""
    import agent.booking.leaves as _self

    booking = dict(state.get("booking") or {})

    if booking.get("customer_full_name"):
        booking["step"] = "notes"
        return Command(goto="route_next", update={"booking": booking})

    system_msg = await build_leaf_system_message("ask_name", booking, state)
    llm = _self.get_llm()
    chain = llm.with_structured_output(NameResponse)
    messages = [system_msg] + _current_messages(state)
    response: NameResponse = await chain.ainvoke(messages)

    if response.first_name and response.first_surname:
        booking["customer_full_name"] = f"{response.first_name} {response.first_surname}"
    elif response.first_name:
        booking["customer_full_name"] = response.first_name

    if booking.get("customer_full_name"):
        booking["step"] = "notes"
        return Command(goto="route_next", update={"booking": booking})

    booking["step"] = "name"
    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=response.message)],
            "booking": booking,
        },
    )


async def ask_notes(state: dict[str, Any]) -> Command:
    """Ask user for any notes or special requests."""
    import agent.booking.leaves as _self

    booking = dict(state.get("booking") or {})

    system_msg = await build_leaf_system_message("ask_notes", booking, state)
    llm = _self.get_llm()
    chain = llm.with_structured_output(NotesResponse)
    messages = [system_msg] + _current_messages(state)
    response: NotesResponse = await chain.ainvoke(messages)

    if not response.user_declined and response.notes:
        booking["notes"] = response.notes
    booking["_notes_asked"] = True
    booking["step"] = "confirm"

    return Command(
        goto=END,
        update={
            "messages": [AIMessage(content=response.message)],
            "booking": booking,
        },
    )
