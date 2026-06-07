"""CustomerResolveMiddleware — phone → Customer DB lookup; inject state delta.

Hook: awrap_model_call
Logic:
  - If state.customer_id already set → skip (idempotent).
  - Else query Customer by phone.
  - If found: inject customer_id + customer_name + memory enrichment into
    a <customer> block appended to the system prompt, and pass state updates
    via request.override().
  - D5: if Customer.notes is non-null, also emit a <customer_staff_notes> block.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from agent.services.customer_memory_service import read_customer_memories
from shared.config import get_settings
from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

_CUSTOMER_CACHE_KEY_FMT = "customer:phone:{phone}"
_AGENT_NOTES_MAX_CHARS = 200
_STAFF_NOTES_MAX_CHARS = 300


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
    """Query Customer by phone. Returns dict with id, name, is_returning, notes or None."""
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
                "phone": customer.phone,
                "is_returning": has_appointments,
                "notes": customer.notes,  # D5: staff notes (allergies/restrictions)
                "policy_accepted_at": customer.policy_accepted_at,  # GDPR consent date
                "policy_version": customer.policy_version,          # version accepted
            }
    except Exception as exc:
        logger.warning("Customer lookup failed for phone %s: %s", phone, exc)
        return None


def _build_memory_lines(memories: dict | None, is_returning: bool) -> list[str]:
    """Build memory-specific bullet lines for <customer> slot per D1 field rules.

    Returns an empty list when memories is None or is_returning is False.
    Field rules (deterministic, in order):
      1. Visitas previas — only if visit_count >= 1
      2. Estilista preferido — only if preferred_stylist_name non-null and no_preference_stylist=False
      3. Servicios habituales — only if list non-empty, capped at 3
      4. Día/franja habitual — only if BOTH typical_day_of_week and typical_time_of_day non-null
      5. Notas del bot — only if non-empty, truncated to 200 chars
    """
    if not memories or not is_returning:
        return []

    lines: list[str] = []

    visit_count = memories.get("visit_count")
    if visit_count and visit_count >= 1:
        lines.append(f"- Visitas previas: {visit_count}")

    preferred_stylist = memories.get("preferred_stylist_name")
    no_pref = memories.get("no_preference_stylist", False)
    if preferred_stylist and not no_pref:
        lines.append(f"- Estilista preferido: {preferred_stylist}")

    typical_services = memories.get("typical_services") or []
    capped_services = typical_services[:3]
    if capped_services:
        lines.append(f"- Servicios habituales: {', '.join(capped_services)}")

    typical_day = memories.get("typical_day_of_week")
    typical_time = memories.get("typical_time_of_day")
    if typical_day and typical_time:
        lines.append(f"- Día/franja habitual: {typical_day} / {typical_time}")

    agent_notes = memories.get("agent_notes")
    if agent_notes and agent_notes.strip():
        truncated = (
            agent_notes[:_AGENT_NOTES_MAX_CHARS] + "…"
            if len(agent_notes) > _AGENT_NOTES_MAX_CHARS
            else agent_notes
        )
        lines.append(f"- Notas del bot: {truncated}")

    return lines


def _build_staff_notes_block(staff_notes: str | None) -> str | None:
    """Build the <customer_staff_notes> block for D5. Returns None when notes absent."""
    if not staff_notes or not staff_notes.strip():
        return None
    truncated = (
        staff_notes[:_STAFF_NOTES_MAX_CHARS] + "…"
        if len(staff_notes) > _STAFF_NOTES_MAX_CHARS
        else staff_notes
    )
    return f"<customer_staff_notes>\n{truncated}\n</customer_staff_notes>"


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

        # Read customer memories fail-open
        try:
            memories = await read_customer_memories(phone)
        except Exception as exc:
            logger.warning("read_customer_memories failed for %s: %s", phone, exc)
            memories = None

        # Build <customer> block for known customers
        returning_label = "Sí" if customer["is_returning"] else "No"
        body_lines = [
            f"- Nombre: {customer['name']}",
            f"- Teléfono: {phone}",
            f"- Cliente recurrente: {returning_label}",
        ]

        # Append memory lines per D1 field rules
        memory_lines = _build_memory_lines(memories, is_returning=customer["is_returning"])
        body_lines.extend(memory_lines)

        # ── Policy line — three states ────────────────────────────────────────
        _settings = get_settings()
        _policy_accepted_at = customer.get("policy_accepted_at")
        _policy_version = customer.get("policy_version")
        if _policy_accepted_at is None:
            body_lines.append("- Política privacidad: no aceptada")
        elif _policy_version == _settings.POLICY_VERSION:
            _accepted_date = _policy_accepted_at.strftime("%d/%m/%Y")
            body_lines.append(
                f"- Política privacidad: aceptada v{_settings.POLICY_VERSION} el {_accepted_date}"
            )
        else:
            _accepted_date = _policy_accepted_at.strftime("%d/%m/%Y")
            body_lines.append(
                f"- Política privacidad: aceptada v{_policy_version} el {_accepted_date}"
                f" (versión obsoleta)"
            )

        slot_parts = [f"<customer>\n{chr(10).join(body_lines)}\n</customer>"]

        # D5: append staff notes block if present
        staff_notes_block = _build_staff_notes_block(customer.get("notes"))
        if staff_notes_block:
            slot_parts.append(staff_notes_block)

        slot = "\n".join(slot_parts)

        # Inject state delta only if not already set
        new_state = {**state, "_slot_customer": slot, "customer_memories": memories}
        if state.get("customer_id") is None:
            new_state["customer_id"] = customer["id"]
        if state.get("customer_name") is None:
            new_state["customer_name"] = customer["name"]
        modified_request = request.override(state=new_state)

        return await handler(modified_request)
