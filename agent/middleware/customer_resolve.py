"""CustomerResolveMiddleware — phone → Customer DB lookup; inject state delta.

Hook: awrap_model_call
Logic:
  - If state.customer_id already set → skip (idempotent).
  - Else query Customer by customer_phone.
  - If found: inject customer_id + customer_name into a ## Cliente block appended
    to the system prompt, and pass state updates via request.override().
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)


async def _lookup_customer(phone: str) -> dict | None:
    """Query Customer by phone. Returns dict with id, name, is_returning or None."""
    try:
        from sqlalchemy import select

        from database.connection import get_async_session
        from database.models import Appointment, Customer

        async with get_async_session() as session:
            result = await session.execute(select(Customer).where(Customer.phone == phone).limit(1))
            customer = result.scalars().first()
            if customer is None:
                return None

            # Check if returning customer (has prior appointments)
            appt_result = await session.execute(
                select(Appointment).where(Appointment.customer_id == customer.id).limit(1)
            )
            has_appointments = appt_result.scalars().first() is not None

            return {
                "id": customer.id,
                "name": customer.name,
                "is_returning": has_appointments,
            }
    except Exception as exc:
        logger.warning("Customer lookup failed for phone %s: %s", phone, exc)
        return None


class CustomerResolveMiddleware(AgentMiddleware):
    """Resolve customer from phone and inject into state + system prompt."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state or {}

        phone = state.get("customer_phone", "")
        if not phone:
            return await handler(request)

        # Always do lookup when phone exists — ensures ## Cliente block is present for booking_flow.md
        # (previously skipped if customer_id already set, but the flow depends on the block being there)
        customer = await _lookup_customer(phone)

        if customer is None:
            # Inject phone-only ## Cliente block for new (unknown) customers
            phone_block = f"\n\n## Cliente\n- Teléfono: {phone}"
            original_content = request.system_message.content if request.system_message else ""
            new_system = SystemMessage(content=original_content + phone_block)
            modified_request = request.override(system_message=new_system)
            return await handler(modified_request)

        # Build ## Cliente block for known customers
        returning_label = "Sí" if customer["is_returning"] else "No"
        customer_block = (
            f"\n\n## Cliente\n"
            f"- Nombre: {customer['name']}\n"
            f"- Teléfono: {phone}\n"
            f"- Cliente recurrente: {returning_label}"
        )
        original_content = request.system_message.content if request.system_message else ""
        new_system = SystemMessage(content=original_content + customer_block)

        # Inject state delta only if not already set
        new_state = {**state}
        if state.get("customer_id") is None:
            new_state["customer_id"] = customer["id"]
        if state.get("customer_name") is None:
            new_state["customer_name"] = customer["name"]
        modified_request = request.override(system_message=new_system, state=new_state)

        return await handler(modified_request)
