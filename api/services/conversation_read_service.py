"""
Conversation read-state service — marks messages as read for inbox operators.

Provides idempotent mark-read: rows that already have ``read_at`` set are
skipped so repeated calls are safe and return 0.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ConversationMessage

logger = logging.getLogger(__name__)


async def mark_messages_read(
    session: AsyncSession,
    conversation_history_id: UUID,
    up_to_message_id: UUID | None = None,
) -> int:
    """Mark unread messages in a conversation as read.

    Updates ``read_at = NOW()`` on ``conversation_messages`` rows where
    ``read_at IS NULL``.  When ``up_to_message_id`` is given, only rows
    created on or before that message's ``created_at`` are updated.

    Args:
        session: Active async SQLAlchemy session.
        conversation_history_id: PK of the parent ``ConversationHistory`` row.
        up_to_message_id: Optional upper-bound message UUID.  When provided,
            only messages up to and including this message are marked read.

    Returns:
        Number of rows updated (0 when all messages were already read).

    Raises:
        ValueError: When ``up_to_message_id`` is provided but does not exist
            in this conversation.
    """
    now = datetime.now(tz=UTC)

    cutoff_at: datetime | None = None
    if up_to_message_id is not None:
        result = await session.execute(
            select(ConversationMessage.created_at).where(
                ConversationMessage.id == up_to_message_id,
                ConversationMessage.conversation_history_id == conversation_history_id,
            )
        )
        cutoff_at = result.scalar_one_or_none()
        if cutoff_at is None:
            raise ValueError(
                f"Message '{up_to_message_id}' not found in conversation "
                f"'{conversation_history_id}'."
            )

    stmt = (
        update(ConversationMessage)
        .where(
            ConversationMessage.conversation_history_id == conversation_history_id,
            ConversationMessage.read_at.is_(None),
        )
        .values(read_at=now)
        .execution_options(synchronize_session="fetch")
    )

    if cutoff_at is not None:
        stmt = stmt.where(ConversationMessage.created_at <= cutoff_at)

    result = await session.execute(stmt)
    updated = result.rowcount or 0

    logger.info(
        "mark_messages_read: conversation_history_id=%s updated=%d up_to=%s",
        conversation_history_id,
        updated,
        up_to_message_id,
    )

    return updated
