"""AgentState TypedDict — slim schema for create_agent MVP rewrite."""

from __future__ import annotations

from typing import Annotated, TypedDict
from uuid import UUID

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    conversation_id: str
    customer_phone: str
    user_message: str | None
    pending_whatsapp_name: str | None
    messages: Annotated[list[AnyMessage], add_messages]
    customer_id: UUID | None
    customer_name: str | None
