"""Preprocess node — Task 6.2 (updated: booking-prompts-audit-fix).

Responsibilities:
1. Reject empty/whitespace messages (Command(goto=END)).
2. Truncate user_message to 2000 chars.
3. Customer lookup by phone → populate customer_id + customer_name.
4. Append user_message as HumanMessage.
5. Return Command(goto="router", update={...}).

Note: First-turn greeting is emitted by the mode node via its system prompt,
NOT injected here. Preprocess never adds AIMessage to state.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.constants import END
from langgraph.types import Command

from database.connection import get_async_session
from database.models import Customer

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LEN = 2000


async def preprocess_node(state: dict[str, Any]) -> Command:
    """Entry node: validates, truncates, looks up customer, appends HumanMessage."""
    user_message: str = (state.get("user_message") or "").strip()

    # 1. Reject empty turns — nothing to process
    if not user_message:
        return Command(goto=END, update={})

    # 2. Truncate to 2000 chars
    if len(user_message) > _MAX_MESSAGE_LEN:
        user_message = user_message[:_MAX_MESSAGE_LEN]

    new_messages: list[Any] = []

    # 3. Append the (possibly truncated) user message
    new_messages.append(HumanMessage(content=user_message))

    # 4. Customer lookup
    customer_id = None
    customer_name = None
    phone = state.get("customer_phone", "")
    if phone:
        try:
            customer_id, customer_name = await _lookup_customer(phone)
        except Exception:
            logger.warning("Customer lookup failed for phone %s", phone, exc_info=True)

    update: dict[str, Any] = {
        "messages": new_messages,
        "user_message": None,
        "customer_id": customer_id,
        "customer_name": customer_name,
    }

    return Command(goto="router", update=update)


async def _lookup_customer(phone: str):
    """Return (customer_id, customer_name) or (None, None) if not found."""
    from sqlalchemy import select

    async with get_async_session() as session:
        result = await session.execute(select(Customer).where(Customer.phone == phone))
        customer = result.scalar_one_or_none()

    if customer is None:
        return None, None
    return customer.id, customer.full_name
