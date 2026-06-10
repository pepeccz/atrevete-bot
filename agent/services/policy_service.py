"""Policy acceptance service — atomic consent persistence.

Provides:
    PolicyConsentError — raised on DB failure; propagates rollback.
    accept_policy — atomically UPDATE Customer + INSERT CustomerConsent.

Design contract (Design §3):
    - Caller opens the transaction (async with get_async_session() as session:).
    - This function flushes but does NOT commit — caller owns commit.
    - Idempotent within a 10-second window: a second call for the same
      (customer_id, policy_version) within 10 seconds returns the existing
      row without re-inserting.
    - Cache invalidation (_invalidate_cached_customer) is called AFTER
      the flush succeeds. If flush raises, cache is NOT invalidated.

Usage example (caller pattern):
    async with get_async_session() as session:
        consent = await accept_policy(
            db=session,
            customer_id=customer.id,
            policy_version=settings.POLICY_VERSION,
            accepted_via="whatsapp",
            source_message_id=state.get("chatwoot_message_id"),
        )
        session.add(appointment)
        await session.commit()
        # Cache already invalidated inside accept_policy after flush succeeded
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.middleware.customer_resolve import _invalidate_cached_customer
from database.models import Customer, CustomerConsent

logger = logging.getLogger(__name__)

# Idempotency window — if a consent for the same (customer_id, policy_version)
# was recorded within this many seconds, return the existing row without re-inserting.
_IDEMPOTENCY_WINDOW_SECONDS = 10

# Conversation-scoped acceptance marker (Change L / L2 — policy re-ask loop).
# Written the moment the customer accepts the policy (update_booking gate clear),
# BEFORE any customers row exists for brand-new customers. Both policy gates
# (update_booking step 6c and book B4) consult it when the LLM drops the
# policy_accepted round-trip flag between tool calls.
_POLICY_MARKER_KEY_FMT = "policy_accepted:v2:{conversation_id}"
_POLICY_MARKER_TTL_SECONDS = 86400  # 24h — outlives any single booking conversation


class PolicyConsentError(Exception):
    """Raised when policy consent persistence fails. Propagates rollback.

    Always wraps the underlying SQLAlchemy exception as __cause__ for
    easy diagnosis in logs.
    """


async def accept_policy(
    db: AsyncSession,
    customer_id: UUID,
    policy_version: str,
    accepted_via: Literal["whatsapp", "admin_panel"],
    source_message_id: str | None = None,
) -> CustomerConsent:
    """Atomically record policy acceptance: UPDATE Customer + INSERT CustomerConsent.

    Idempotent: if a consent row exists for (customer_id, policy_version)
    within the last 10 seconds, returns it without re-writing.

    Flushes (but does NOT commit) the session so changes participate in the
    caller's transaction. Cache invalidation fires AFTER successful flush;
    it is NOT called when a DB error is raised.

    Args:
        db: Active AsyncSession (caller owns transaction lifecycle).
        customer_id: UUID of the Customer accepting the policy.
        policy_version: Opaque version string (e.g. "1.0").
        accepted_via: Channel through which acceptance was given.
        source_message_id: Optional Chatwoot message ID for traceability.

    Returns:
        The CustomerConsent row (new or existing within idempotency window).

    Raises:
        PolicyConsentError: Wraps underlying SQLAlchemy error. Caller's
            async-with block will roll back the transaction.
    """
    try:
        # ── Fetch customer (needed for phone + UPDATE) ──────────────────────
        customer = await db.get(Customer, customer_id)

        # ── Idempotency check ───────────────────────────────────────────────
        # Look up the most recent consent row for this (customer, version).
        # If it was created within the idempotency window, short-circuit.
        now = datetime.now(UTC)
        window_start = now - timedelta(seconds=_IDEMPOTENCY_WINDOW_SECONDS)

        result = await db.execute(
            select(CustomerConsent)
            .where(CustomerConsent.customer_id == customer_id)
            .where(CustomerConsent.policy_version == policy_version)
            .order_by(CustomerConsent.accepted_at.desc())
            .limit(1)
        )
        existing = result.scalars().first()

        if existing is not None and existing.accepted_at >= window_start:
            logger.info(
                "policy_service.accept_policy: idempotency hit — returning existing consent",
                extra={
                    "customer_id": str(customer_id),
                    "policy_version": policy_version,
                    "age_seconds": (now - existing.accepted_at).total_seconds(),
                },
            )
            # Still invalidate cache — caller may have changed customer state
            if customer is not None:
                await _invalidate_cached_customer(customer.phone)
            return existing

        # ── Write: UPDATE Customer ──────────────────────────────────────────
        if customer is not None:
            customer.policy_accepted_at = now
            customer.policy_version = policy_version

        # ── Write: INSERT CustomerConsent ───────────────────────────────────
        consent = CustomerConsent(
            customer_id=customer_id,
            policy_version=policy_version,
            accepted_at=now,
            accepted_via=accepted_via,
            source_message_id=source_message_id,
        )
        db.add(consent)

        # ── Flush (stage changes in transaction; caller commits) ────────────
        await db.flush()

        logger.info(
            "policy_service.accept_policy: consent recorded",
            extra={
                "customer_id": str(customer_id),
                "policy_version": policy_version,
                "accepted_via": accepted_via,
                "consent_id": str(consent.id) if consent.id else "pending",
            },
        )

    except SQLAlchemyError as exc:
        logger.error(
            "policy_service.accept_policy: DB error — rolling back",
            extra={"customer_id": str(customer_id), "error": str(exc)},
        )
        raise PolicyConsentError(
            f"Failed to persist policy consent for customer {customer_id}: {exc}"
        ) from exc

    # ── Cache invalidation (AFTER flush succeeds, BEFORE returning) ─────────
    # Fire-and-forget: fail-open so a Redis error never blocks the booking flow.
    if customer is not None:
        await _invalidate_cached_customer(customer.phone)

    return consent


# ---------------------------------------------------------------------------
# Conversation acceptance marker (Change L / L2) — all helpers fail-open
# ---------------------------------------------------------------------------


async def set_conversation_policy_acceptance(conversation_id: str, policy_version: str) -> None:
    """Persist a conversation-scoped acceptance marker in Redis (fail-open).

    Durable fallback for the policy gates: once the customer says "sí" the
    acceptance must survive a dropped LLM round-trip flag. The marker covers
    brand-new customers that have no customers row until book() creates one.
    """
    try:
        from shared.redis_client import get_redis_client

        client = get_redis_client()
        await client.setex(
            _POLICY_MARKER_KEY_FMT.format(conversation_id=conversation_id),
            _POLICY_MARKER_TTL_SECONDS,
            policy_version,
        )
    except Exception as exc:
        logger.warning("policy acceptance marker SETEX failed conv=%s: %s", conversation_id, exc)


async def get_conversation_policy_acceptance(conversation_id: str) -> str | None:
    """Return the policy version accepted in this conversation, or None (fail-open)."""
    try:
        from shared.redis_client import get_redis_client

        client = get_redis_client()
        raw = await client.get(_POLICY_MARKER_KEY_FMT.format(conversation_id=conversation_id))
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)
    except Exception as exc:
        logger.warning("policy acceptance marker GET failed conv=%s: %s", conversation_id, exc)
        return None


async def clear_conversation_policy_acceptance(conversation_id: str) -> None:
    """Delete the conversation acceptance marker after the consent row is committed."""
    try:
        from shared.redis_client import get_redis_client

        client = get_redis_client()
        await client.delete(_POLICY_MARKER_KEY_FMT.format(conversation_id=conversation_id))
    except Exception as exc:
        logger.warning("policy acceptance marker DEL failed conv=%s: %s", conversation_id, exc)
