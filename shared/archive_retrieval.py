"""
Archive retrieval functionality for accessing historical conversations.

This module provides functions to retrieve archived conversations from PostgreSQL
using the two-table schema (ConversationHistory parent + ConversationMessage children).

API response shapes are kept backward-compatible with the old flat-table implementation
so that downstream callers (api/routes/conversations.py) require no changes.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.connection import get_async_session
from database.models import ConversationHistory, ConversationMessage

logger = logging.getLogger(__name__)


async def get_archived_conversation(
    conversation_id: str,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Retrieve archived conversation messages from PostgreSQL.

    This function queries the two-table schema (ConversationHistory + ConversationMessage)
    to fetch messages for a specific conversation that has been archived (>24h old).

    Args:
        conversation_id: The conversation ID (thread_id / Chatwoot conversation ID)
        limit: Maximum number of messages to return (default: 100)
        offset: Number of messages to skip for pagination (default: 0)

    Returns:
        Dict containing:
        - conversation_id: str
        - customer_phone: str | None
        - messages: list[dict] — Message history with role, content, timestamp
        - total_messages: int — Total count of messages in archive
        - has_more: bool — Whether there are more messages beyond limit+offset

    Example:
        >>> result = await get_archived_conversation("wa-msg-123", limit=50)
        >>> print(f"Found {result['total_messages']} messages")
        >>> for msg in result['messages']:
        ...     print(f"{msg['role']}: {msg['content'][:50]}")
    """
    try:
        async with get_async_session() as session:
            # Load the parent ConversationHistory row (with customer relationship)
            stmt = (
                select(ConversationHistory)
                .where(ConversationHistory.conversation_id == conversation_id)
                .options(selectinload(ConversationHistory.customer))
            )
            result = await session.execute(stmt)
            parent: ConversationHistory | None = result.scalar_one_or_none()

            if parent is None:
                logger.info(f"No archived conversation found for ID: {conversation_id}")
                return {
                    "conversation_id": conversation_id,
                    "customer_phone": None,
                    "messages": [],
                    "total_messages": 0,
                    "has_more": False,
                }

            total_messages: int = parent.message_count

            # Get customer phone (via relationship)
            customer_phone: str | None = None
            if parent.customer:
                customer_phone = parent.customer.phone

            # Query paginated ConversationMessage children
            msg_stmt = (
                select(ConversationMessage)
                .where(ConversationMessage.conversation_history_id == parent.id)
                .order_by(ConversationMessage.created_at.asc())
                .offset(offset)
                .limit(limit)
            )
            msg_result = await session.execute(msg_stmt)
            message_records = msg_result.scalars().all()

            # Format messages — same shape as old flat-table implementation
            messages = [
                {
                    "role": record.role,
                    "content": record.content,
                    "timestamp": record.created_at.isoformat(),
                }
                for record in message_records
            ]

            has_more = (offset + limit) < total_messages

            logger.info(
                f"Retrieved {len(messages)} messages from archive "
                f"(total: {total_messages}, conversation_id: {conversation_id})"
            )

            return {
                "conversation_id": conversation_id,
                "customer_phone": customer_phone,
                "messages": messages,
                "total_messages": total_messages,
                "has_more": has_more,
            }

    except Exception as e:
        logger.error(
            f"Error retrieving archived conversation {conversation_id}: {e}",
            exc_info=True,
        )
        raise


async def list_archived_conversations(
    customer_phone: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    List archived conversations with optional filtering.

    Queries the ConversationHistory parent table directly — no GROUP BY needed
    because the new schema has exactly one parent row per conversation.

    Args:
        customer_phone: Filter by customer phone number (E.164 format)
        start_date: Filter conversations started after this date
        end_date: Filter conversations started before this date
        limit: Maximum number of conversations to return
        offset: Number of conversations to skip for pagination

    Returns:
        Dict containing:
        - conversations: list[dict] — List of conversation summaries
        - total_count: int — Total matching conversations
        - has_more: bool — Whether there are more results

    Example:
        >>> result = await list_archived_conversations(
        ...     customer_phone="+34612345678",
        ...     limit=20
        ... )
        >>> print(f"Found {result['total_count']} conversations")
    """
    try:
        from database.models import Customer

        async with get_async_session() as session:
            # Build the base query over ConversationHistory (one row per conversation)
            stmt = (
                select(ConversationHistory)
                .options(selectinload(ConversationHistory.customer))
                .order_by(ConversationHistory.started_at.desc())
            )

            # Filter by customer phone (join Customer)
            if customer_phone:
                stmt = (
                    stmt.join(Customer, ConversationHistory.customer_id == Customer.id)
                    .where(Customer.phone == customer_phone)
                )

            # Filter by date range on started_at
            if start_date:
                stmt = stmt.where(ConversationHistory.started_at >= start_date)
            if end_date:
                stmt = stmt.where(ConversationHistory.started_at <= end_date)

            # Execute to get total count + all rows (for in-memory pagination)
            count_result = await session.execute(stmt)
            all_rows: list[ConversationHistory] = list(count_result.scalars().all())
            total_count = len(all_rows)

            # Apply pagination
            paginated: list[ConversationHistory] = all_rows[offset : offset + limit]
            has_more = (offset + limit) < total_count

            # Format results — backward-compatible shape with old flat-table response
            conversations = [
                {
                    "conversation_id": row.conversation_id,
                    "customer_phone": row.customer.phone if row.customer else None,
                    "created_at": row.started_at.isoformat() if row.started_at else None,
                    "message_count": row.message_count,
                    "has_summary": row.summary is not None,
                }
                for row in paginated
            ]

            logger.info(
                f"Listed {len(conversations)} archived conversations "
                f"(total: {total_count}, customer_phone: {customer_phone})"
            )

            return {
                "conversations": conversations,
                "total_count": total_count,
                "has_more": has_more,
            }

    except Exception as e:
        logger.error(
            f"Error listing archived conversations: {e}",
            exc_info=True,
        )
        raise
