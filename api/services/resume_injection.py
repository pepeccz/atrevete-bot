"""
Resume injection service — injects paused-window messages into LangGraph state.

When a conversation is resumed after a bot-pause period, any messages exchanged
during the pause (human-agent outbound + customer inbound) need to be injected
into the LangGraph checkpointer state so the agent has full context on the next
turn.

Design (ADR-1, ADR-2):
  - The /resume endpoint sets a Redis flag ``pending_injection:v2:{conv_id}``
    with TTL 600s (deferred injection — we don't inject at resume time).
  - On the NEXT inbound webhook from the customer, ``maybe_inject_pending_context``
    is called BEFORE the Redis Stream publish step.
  - If the flag exists, this function acquires a SETNX lock, fetches paused-window
    messages, calls ``graph.aupdate_state()``, marks the injection timestamp, and
    deletes the flag.
  - Idempotency: ``ConversationHistory.context_injected_at >= resumed_at`` means
    injection already happened for this resume cycle — skip.
  - Race safety (R1): SETNX lock prevents concurrent injections; if lock is held,
    the second caller polls for up to 2s then proceeds without re-injecting.

Usage (called from api/routes/chatwoot.py)::

    from api.services.resume_injection import maybe_inject_pending_context

    did_inject = await maybe_inject_pending_context(
        conversation_id=str(payload.conversation.id),
        session=db_session,
        redis_client=redis_client,
    )
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ConversationHistory, ConversationMessage, ConversationMessageRole

logger = logging.getLogger(__name__)

# Redis key templates
_PENDING_INJECTION_KEY = "pending_injection:v2:{conv_id}"
_INJECTION_LOCK_KEY = "pending_injection_lock:v2:{conv_id}"

# Lock TTL (seconds) — must be long enough for aupdate_state() to complete
_LOCK_TTL_SECONDS = 10

# How long the loser of the lock acquisition waits for the winner to finish (seconds)
_LOCK_WAIT_SECONDS = 2.0
_LOCK_POLL_INTERVAL_SECONDS = 0.1


async def maybe_inject_pending_context(
    conversation_id: str,
    session: AsyncSession,
    redis_client: Any,
) -> bool:
    """Check for a pending injection flag and perform context injection if needed.

    Implements the full ADR-1/ADR-2 deferred injection sequence:
    1. Check Redis for ``pending_injection:v2:{conv_id}``. If absent → return False.
    2. Acquire SETNX lock ``pending_injection_lock:v2:{conv_id}`` (TTL 10s).
    3. If lock not acquired: poll up to 2s for ``context_injected_at`` to be set by
       the sibling call; if still null after 2s, log warning and return False.
    4. Re-check idempotency: skip if ``context_injected_at >= resumed_at``.
    5. Fetch paused-window ``ConversationMessage`` rows (ascending ``created_at``).
    6. Build LangChain message list (HumanMessage for 'user', AIMessage for 'human_agent').
    7. Open short-lived ``AsyncRedisSaver`` context manager (NFR-5).
    8. Call ``graph.aupdate_state()`` with the messages.
    9. Set ``ConversationHistory.context_injected_at = NOW()``, commit.
    10. Release lock. Delete ``pending_injection`` flag. Return True.

    Args:
        conversation_id: The Chatwoot / LangGraph conversation identifier string.
        session: Active async SQLAlchemy session for this request.
        redis_client: Redis client used for flag/lock operations.

    Returns:
        ``True`` if injection was performed (or already done), ``False`` if
        no pending flag existed or injection was skipped due to lock timeout.
    """
    pending_key = _PENDING_INJECTION_KEY.format(conv_id=conversation_id)
    lock_key = _INJECTION_LOCK_KEY.format(conv_id=conversation_id)

    # Step 1: Check for pending flag
    flag_exists = await redis_client.exists(pending_key)
    if not flag_exists:
        return False

    # Step 2: Acquire SETNX lock
    got_lock = await redis_client.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)

    if not got_lock:
        # Step 3: A sibling webhook is mid-injection — wait up to 2s for it to finish
        logger.info(
            "pending_injection lock already held — waiting for sibling injection to complete",
            extra={"conversation_id": conversation_id},
        )
        deadline = asyncio.get_event_loop().time() + _LOCK_WAIT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(_LOCK_POLL_INTERVAL_SECONDS)
            # Refresh the history row to pick up the sibling's commit
            result = await session.execute(
                select(ConversationHistory).where(
                    ConversationHistory.conversation_id == conversation_id
                )
            )
            history = result.scalar_one_or_none()
            if history is not None and _injection_done(history):
                logger.info(
                    "Sibling injection completed — skipping duplicate injection",
                    extra={"conversation_id": conversation_id},
                )
                return False

        logger.warning(
            "pending_injection_lock not released in %.1fs — proceeding without injection",
            _LOCK_WAIT_SECONDS,
            extra={"conversation_id": conversation_id},
        )
        return False

    # We hold the lock — perform injection
    try:
        return await _do_injection(
            conversation_id=conversation_id,
            session=session,
            redis_client=redis_client,
            pending_key=pending_key,
            lock_key=lock_key,
        )
    except Exception:
        # On unexpected error, release the lock so the next inbound can retry
        logger.exception(
            "Unexpected error during resume injection",
            extra={"conversation_id": conversation_id},
        )
        try:
            await redis_client.delete(lock_key)
        except Exception:  # noqa: BLE001
            pass
        return False


def _injection_done(history: ConversationHistory) -> bool:
    """Return True if context has already been injected for the current resume cycle."""
    if history.context_injected_at is None or history.resumed_at is None:
        return False
    ci = history.context_injected_at
    ra = history.resumed_at
    # Ensure both are timezone-aware for comparison
    if ci.tzinfo is None:
        ci = ci.replace(tzinfo=UTC)
    if ra.tzinfo is None:
        ra = ra.replace(tzinfo=UTC)
    return ci >= ra


async def _do_injection(
    conversation_id: str,
    session: AsyncSession,
    redis_client: Any,
    pending_key: str,
    lock_key: str,
) -> bool:
    """Perform the actual injection — called only by the lock holder.

    This function is responsible for releasing the lock (via ``finally``)
    and deleting the pending flag on success.
    """
    try:
        # Step 4: Idempotency check
        result = await session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        history = result.scalar_one_or_none()
        if history is None:
            logger.warning(
                "ConversationHistory not found for injection — skipping",
                extra={"conversation_id": conversation_id},
            )
            return False

        if _injection_done(history):
            logger.info(
                "context_injected_at >= resumed_at — skipping duplicate injection",
                extra={"conversation_id": conversation_id},
            )
            # Clean up the stale flag
            await redis_client.delete(pending_key)
            return False

        # Step 5: Fetch paused-window messages in ascending order
        # Anchor: messages created at or after paused_at
        # (COALESCE to resumed_at - 10min if paused_at is null)
        if history.paused_at is not None:
            anchor = history.paused_at
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=UTC)
        elif history.resumed_at is not None:
            from datetime import timedelta

            ra = history.resumed_at
            if ra.tzinfo is None:
                ra = ra.replace(tzinfo=UTC)
            anchor = ra - timedelta(minutes=10)
        else:
            logger.warning(
                "No paused_at or resumed_at — cannot determine injection window; skipping",
                extra={"conversation_id": conversation_id},
            )
            return False

        msgs_result = await session.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_history_id == history.id,
                ConversationMessage.created_at >= anchor,
                ConversationMessage.role.in_(
                    [
                        ConversationMessageRole.USER.value,
                        ConversationMessageRole.HUMAN_AGENT.value,
                    ]
                ),
            )
            .order_by(ConversationMessage.created_at)
        )
        db_messages = msgs_result.scalars().all()

        if not db_messages:
            logger.info(
                "No paused-window messages to inject — cleaning up flag",
                extra={"conversation_id": conversation_id},
            )
            await redis_client.delete(pending_key)
            return False

        # Step 6: Build LangChain message list
        lc_messages = []
        for m in db_messages:
            if m.role == ConversationMessageRole.HUMAN_AGENT.value:
                lc_messages.append(
                    AIMessage(
                        content=m.content or "",
                        additional_kwargs={
                            "author": "human_agent",
                            "author_user_id": str(m.author_user_id) if m.author_user_id else None,
                        },
                    )
                )
            elif m.role == ConversationMessageRole.USER.value:
                lc_messages.append(
                    HumanMessage(
                        content=m.content or "",
                        additional_kwargs={"author": "customer"},
                    )
                )

        logger.info(
            "Injecting %d paused-window messages into LangGraph state",
            len(lc_messages),
            extra={"conversation_id": conversation_id},
        )

        # Steps 7–8: Short-lived AsyncRedisSaver + aupdate_state
        thread_id = f"v2:{conversation_id}"
        graph_config = {"configurable": {"thread_id": thread_id}}

        from agent.agent_factory import build_conversation_agent
        from shared.checkpointer import get_checkpointer

        async with get_checkpointer() as saver:
            graph = build_conversation_agent(checkpointer=saver)
            await graph.aupdate_state(graph_config, {"messages": lc_messages})

        # Step 9: Mark injection done
        now = datetime.now(tz=UTC)
        history.context_injected_at = now
        await session.commit()

        # Step 10: Delete the pending flag
        await redis_client.delete(pending_key)

        logger.info(
            "Resume injection complete — context_injected_at set",
            extra={
                "conversation_id": conversation_id,
                "injected_message_count": len(lc_messages),
                "context_injected_at": now.isoformat(),
            },
        )
        return True

    finally:
        # Always release the lock regardless of outcome
        try:
            await redis_client.delete(lock_key)
        except Exception:  # noqa: BLE001
            pass
