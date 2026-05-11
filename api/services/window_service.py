"""
Window service — computes whether a WhatsApp 24h messaging window is open.

The WhatsApp Business API allows free-text outbound messages only within 24 hours
of the last customer-sent (role='user') message. After that window, only approved
Meta templates may be sent.

Two-tier source of truth:

1. **Cached Chatwoot ``can_reply``** mirrored on the ``ConversationHistory`` row
   by the inbound webhook. This is the same value Chatwoot's own UI uses
   (``Conversations::MessageWindowService#can_reply?``), so it's channel-aware
   and authoritative when fresh.

2. **Legacy message-timestamp fallback** (``MAX(created_at) WHERE role='user'``)
   used when the cached value is missing, NULL, or older than 24h (i.e. likely
   stale because no inbound has refreshed it).

Pure read-side service: queries the DB, no writes, no side effects.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    ConversationHistory,
    ConversationMessage,
    ConversationMessageRole,
)

# The WhatsApp customer-service window duration
WINDOW_DURATION = timedelta(hours=24)


async def compute_window_open(
    session: AsyncSession,
    conversation_history_id: UUID,
) -> tuple[bool, datetime | None]:
    """Return whether the 24h WhatsApp messaging window is open for a conversation.

    Prefers the cached ``can_reply`` from Chatwoot when its capture is fresh
    (< 24h old). Falls back to ``MAX(created_at) WHERE role='user'`` otherwise.

    Args:
        session: An active async SQLAlchemy session.
        conversation_history_id: The PK of the ``ConversationHistory`` row
            (NOT the ``conversation_id`` string — the internal UUID).

    Returns:
        A ``(window_open, last_user_message_at)`` tuple where:
        - ``window_open`` is ``True`` if the window is open per the cached
          ``can_reply`` (when fresh) or the message-timestamp fallback.
        - ``last_user_message_at`` is the UTC timestamp of the most recent user
          message, or ``None`` if no user messages exist.
    """
    now = datetime.now(tz=UTC)

    # Tier 1: Cached can_reply mirror from Chatwoot webhook.
    cached_result = await session.execute(
        select(
            ConversationHistory.can_reply,
            ConversationHistory.can_reply_captured_at,
        ).where(ConversationHistory.id == conversation_history_id)
    )
    cached_row = cached_result.first()

    last_user_message_at = await _fetch_last_user_message_at(session, conversation_history_id)

    if cached_row is not None:
        can_reply, captured_at = cached_row
        if can_reply is not None and captured_at is not None:
            captured_at_aware = (
                captured_at if captured_at.tzinfo is not None else captured_at.replace(tzinfo=UTC)
            )
            # Fresh cache: trust Chatwoot's verdict.
            if (now - captured_at_aware) < WINDOW_DURATION:
                return can_reply, last_user_message_at

    # Tier 2: Legacy message-timestamp computation.
    if last_user_message_at is None:
        return False, None

    window_open = (now - last_user_message_at) < WINDOW_DURATION
    return window_open, last_user_message_at


async def _fetch_last_user_message_at(
    session: AsyncSession,
    conversation_history_id: UUID,
) -> datetime | None:
    """Return MAX(created_at) for role='user' messages on this conversation."""
    result = await session.execute(
        select(func.max(ConversationMessage.created_at)).where(
            ConversationMessage.conversation_history_id == conversation_history_id,
            ConversationMessage.role == ConversationMessageRole.USER.value,
        )
    )
    last_user_message_at: datetime | None = result.scalar_one_or_none()
    if last_user_message_at is not None and last_user_message_at.tzinfo is None:
        last_user_message_at = last_user_message_at.replace(tzinfo=UTC)
    return last_user_message_at
