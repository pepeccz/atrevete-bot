"""Daily reminder handler for conversations paused > 24 hours.

Dispatches an in-app Notification to all active admin/stylist users who have
the ``conversations:read`` permission (i.e. all active AdminUser rows, since
every role in ROLE_PERMISSIONS has that permission).

Deduplication: a conversation is eligible only when no
``CONVERSATION_PAUSED_REMINDER`` Notification row exists for it within the
last 24 hours. This prevents duplicate sends without requiring a new DB column
on ConversationHistory.

SC-8, conversaciones-inbox decision obs #5348.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.workers.notification_handlers.base import NotificationHandler
from database.models import AdminUser, ConversationHistory, Notification, NotificationType

logger = logging.getLogger(__name__)

# Conversations that have been paused for at least this long are eligible.
PAUSED_THRESHOLD = timedelta(hours=24)
# Do not re-notify if a reminder was sent within this window.
REMINDER_COOLDOWN = timedelta(hours=24)
BATCH_LIMIT = 50


async def query_fn(session: AsyncSession) -> list[ConversationHistory]:
    """Return conversations paused > 24h with no recent reminder notification.

    A conversation qualifies when:
    - ``paused_at IS NOT NULL`` (bot is paused)
    - ``paused_at <= NOW() - 24h`` (paused for at least 24h)
    - No ``conversation_paused_reminder`` Notification row exists for this
      conversation's ``entity_id`` in the last 24h.
    """
    now = datetime.now(UTC)
    threshold = now - PAUSED_THRESHOLD
    cooldown_cutoff = now - REMINDER_COOLDOWN

    # Sub-query: conversation UUIDs that already have a recent reminder.
    already_reminded_sq = (
        select(Notification.entity_id)
        .where(
            and_(
                Notification.entity_type == "conversation_history",
                Notification.type == NotificationType.CONVERSATION_PAUSED_REMINDER,
                Notification.created_at >= cooldown_cutoff,
            )
        )
        .scalar_subquery()
    )

    stmt = (
        select(ConversationHistory)
        .where(
            and_(
                ConversationHistory.paused_at.is_not(None),
                ConversationHistory.paused_at <= threshold,
                # resumed_at IS NULL means still paused (not just paused at some point)
                ConversationHistory.resumed_at.is_(None),
                ConversationHistory.id.not_in(already_reminded_sq),
            )
        )
        .order_by(ConversationHistory.paused_at.asc())
        .limit(BATCH_LIMIT)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def send_fn(conversation: ConversationHistory, _chatwoot_client: Any) -> bool:
    """Insert in-app Notification rows for all active admin users.

    Uses a fresh session obtained inside the function (needed because the
    worker's process_handler manages session lifecycle separately for query
    and mark phases, but send_fn receives the item without a session).

    Returns True when at least one Notification row was created.
    """
    from database.connection import get_async_session

    customer_label = conversation.customer_id or conversation.conversation_id
    paused_since = ""
    if conversation.paused_at:
        delta = datetime.now(UTC) - conversation.paused_at.replace(tzinfo=UTC)
        hours = int(delta.total_seconds() / 3600)
        paused_since = f" (hace {hours}h)"

    try:
        async with get_async_session() as session:
            # Fetch all active admin users — all roles have conversations:read
            users_stmt = select(AdminUser).where(AdminUser.is_active.is_(True))
            users_result = await session.execute(users_stmt)
            users = list(users_result.scalars().all())

            if not users:
                logger.warning(
                    "paused_24h: no active admin users to notify for conversation %s",
                    conversation.id,
                )
                return False

            notifications = [
                Notification(
                    id=uuid4(),
                    type=NotificationType.CONVERSATION_PAUSED_REMINDER,
                    title="Conversación pausada más de 24h",
                    message=(
                        f"La conversación con el cliente {customer_label}{paused_since} "
                        "sigue pausada. Recuerda reanudar el bot cuando hayas terminado."
                    ),
                    entity_type="conversation_history",
                    entity_id=conversation.id,
                    is_read=False,
                    is_starred=False,
                )
                for _ in users  # one notification per active user (fan-out)
            ]
            session.add_all(notifications)
            await session.commit()
            logger.info(
                "paused_24h: created %d reminder notifications for conversation %s",
                len(notifications),
                conversation.id,
            )
            return True
    except Exception:
        logger.exception(
            "paused_24h: failed to create notification for conversation %s", conversation.id
        )
        return False


async def mark_sent_fn(session: AsyncSession, conversation_id: UUID) -> None:
    """No-op: the Notification row was created atomically inside send_fn.

    The deduplication guard in query_fn (checking Notification.created_at)
    prevents re-notification without a separate mark column.
    """
    # Intentional no-op — state is stored in the Notification table.
    _ = conversation_id


async def mark_failed_fn(session: AsyncSession, conversation_id: UUID) -> None:
    """No-op: we do not penalise ConversationHistory rows on reminder failure.

    The conversation remains eligible on the next worker run. The exponential
    backoff mechanism used for Appointment handlers is not needed here because
    the 24h cooldown in query_fn provides natural debouncing.
    """
    _ = conversation_id


HANDLER = NotificationHandler(
    name="paused_24h",
    query_fn=query_fn,
    send_fn=send_fn,
    mark_sent_fn=mark_sent_fn,
    mark_failed_fn=mark_failed_fn,
)
