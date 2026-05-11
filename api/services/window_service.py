"""
Window service — computes whether a WhatsApp 24h messaging window is open.

The WhatsApp Business API allows free-text outbound messages only within 24 hours
of the last customer-sent (role='user') message. After that window, only approved
Meta templates may be sent.

This module is a pure read-side service: it queries the DB and returns a boolean
alongside the timestamp of the last user message.  No writes, no side effects.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ConversationMessage, ConversationMessageRole

# The WhatsApp customer-service window duration
WINDOW_DURATION = timedelta(hours=24)


async def compute_window_open(
    session: AsyncSession,
    conversation_history_id: UUID,
) -> tuple[bool, datetime | None]:
    """Return whether the 24h WhatsApp messaging window is open for a conversation.

    The window is computed server-side from the DB (not from Chatwoot) per FR-API-4
    and SC-4: ``MAX(created_at) WHERE role='user'`` is compared against ``NOW()``.

    Args:
        session: An active async SQLAlchemy session.
        conversation_history_id: The PK of the ``ConversationHistory`` row
            (NOT the ``conversation_id`` string — the internal UUID).

    Returns:
        A ``(window_open, last_user_message_at)`` tuple where:
        - ``window_open`` is ``True`` if the last user message was within 24 hours.
        - ``last_user_message_at`` is the UTC timestamp of that message, or
          ``None`` if no user messages exist (window is considered closed).

    Example::

        open_, last_msg = await compute_window_open(session, conv_history_id)
        if not open_:
            # offer template picker instead of free-text composer
            ...
    """
    result = await session.execute(
        select(func.max(ConversationMessage.created_at)).where(
            ConversationMessage.conversation_history_id == conversation_history_id,
            ConversationMessage.role == ConversationMessageRole.USER.value,
        )
    )
    last_user_message_at: datetime | None = result.scalar_one_or_none()

    if last_user_message_at is None:
        # No user messages exist — treat window as closed (cannot send free-text first)
        return False, None

    # Ensure the timestamp is timezone-aware (Postgres TIMESTAMPTZ always returns UTC)
    if last_user_message_at.tzinfo is None:
        last_user_message_at = last_user_message_at.replace(tzinfo=UTC)

    now = datetime.now(tz=UTC)
    window_open = (now - last_user_message_at) < WINDOW_DURATION

    return window_open, last_user_message_at
