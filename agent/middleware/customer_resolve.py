"""CustomerResolveMiddleware — phone → Customer DB lookup; inject state delta.

Hook: awrap_model_call
Logic:
  - If state.customer_id already set → skip (idempotent).
  - Else query Customer by customer_phone.
  - If found: inject customer_id + customer_name into a ## Cliente block appended
    to the system prompt, and pass state updates via request.override().
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

_CUSTOMER_CACHE_KEY_FMT = "customer:phone:{phone}"


async def _get_cached_customer(phone: str) -> dict | None:
    """Fail-open Redis GET. Returns parsed dict or None on miss/error."""
    try:
        client = get_redis_client()
        raw = await client.get(_CUSTOMER_CACHE_KEY_FMT.format(phone=phone))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("customer cache GET failed phone=…: %s", exc)
        return None


async def _set_cached_customer(phone: str, data: dict) -> None:
    """Fail-open Redis SETEX with configured TTL."""
    try:
        from shared.config import get_settings

        client = get_redis_client()
        ttl = get_settings().CUSTOMER_CACHE_TTL_SECONDS
        await client.setex(
            _CUSTOMER_CACHE_KEY_FMT.format(phone=phone),
            ttl,
            json.dumps(data, default=str),
        )
    except Exception as exc:
        logger.warning("customer cache SETEX failed phone=…: %s", exc)


async def _invalidate_cached_customer(phone: str) -> None:
    """Fail-open Redis DEL. Called by name-write paths and admin edits."""
    try:
        client = get_redis_client()
        await client.delete(_CUSTOMER_CACHE_KEY_FMT.format(phone=phone))
    except Exception as exc:
        logger.warning("customer cache DEL failed phone=…: %s", exc)


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
    """Resolve customer from phone and inject into state + system prompt.

    Async-only: the customer lookup is async SQLAlchemy against the DB. A
    sync variant would require a duplicate sync DB path that the runtime
    never exercises. Opt out of the parity guardrail.
    """

    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state or {}

        phone = state.get("customer_phone", "")
        if not phone:
            return await handler(request)

        # Cache-aside: attempt Redis GET before DB
        customer = await _get_cached_customer(phone)
        if customer is None:
            customer = await _lookup_customer(phone)
            if customer is not None:
                await _set_cached_customer(phone, customer)

        if customer is None:
            # Phone-only <customer> block for new (unknown) customers
            body = f"- Teléfono: {phone}"
            slot = f"<customer>\n{body}\n</customer>"
            new_state = {**state, "_slot_customer": slot}
            modified_request = request.override(state=new_state)
            return await handler(modified_request)

        # Build <customer> block for known customers
        returning_label = "Sí" if customer["is_returning"] else "No"
        body = (
            f"- Nombre: {customer['name']}\n"
            f"- Teléfono: {phone}\n"
            f"- Cliente recurrente: {returning_label}"
        )
        slot = f"<customer>\n{body}\n</customer>"

        # Inject state delta only if not already set
        new_state = {**state, "_slot_customer": slot}
        if state.get("customer_id") is None:
            new_state["customer_id"] = customer["id"]
        if state.get("customer_name") is None:
            new_state["customer_name"] = customer["name"]
        modified_request = request.override(state=new_state)

        return await handler(modified_request)
