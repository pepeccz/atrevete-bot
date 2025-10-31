"""
Archive retrieval functionality for accessing historical conversations.

This module provides functions to retrieve archived conversations from PostgreSQL
that are older than 24 hours and have been removed from Redis checkpoints.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import ConversationHistory

logger = logging.getLogger(__name__)


async def get_archived_conversation(
    conversation_id: str,
    limit: int = 100,
    offset: int = 0
) -> dict[str, Any]:
    """
    Retrieve archived conversation messages from PostgreSQL.

    This function queries the ConversationHistory table to fetch messages
    for a specific conversation that has been archived (>24h old).

    Args:
        conversation_id: The conversation ID (thread_id) to retrieve
        limit: Maximum number of messages to return (default: 100)
        offset: Number of messages to skip for pagination (default: 0)

    Returns:
        Dict containing:
        - conversation_id: str
        - customer_phone: str | None
        - messages: list[dict] - Message history with role, content, timestamp
        - total_messages: int - Total count of messages in archive
        - has_more: bool - Whether there are more messages beyond limit

    Example:
        >>> result = await get_archived_conversation("wa-msg-123", limit=50)
        >>> print(f"Found {result['total_messages']} messages")
        >>> for msg in result['messages']:
        ...     print(f"{msg['role']}: {msg['content'][:50]}")
    """
    try:
        async for session in get_async_session():
            # Count total messages
            count_stmt = (
                select(ConversationHistory)
                .where(ConversationHistory.conversation_id == conversation_id)
            )
            count_result = await session.execute(count_stmt)
            all_records = count_result.scalars().all()
            total_messages = len(all_records)

            if total_messages == 0:
                logger.info(f"No archived conversation found for ID: {conversation_id}")
                return {
                    "conversation_id": conversation_id,
                    "customer_phone": None,
                    "messages": [],
                    "total_messages": 0,
                    "has_more": False,
                }

            # Query for paginated messages
            stmt = (
                select(ConversationHistory)
                .where(ConversationHistory.conversation_id == conversation_id)
                .order_by(ConversationHistory.timestamp.asc())
                .offset(offset)
                .limit(limit)
            )

            result = await session.execute(stmt)
            records = result.scalars().all()

            # Get customer phone from first record (via relationship)
            customer_phone = None
            if records and records[0].customer:
                customer_phone = records[0].customer.phone

            # Format messages
            messages = []
            for record in records:
                messages.append({
                    "role": record.message_role.value,
                    "content": record.message_content,
                    "timestamp": record.timestamp.isoformat(),
                })

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
            exc_info=True
        )
        raise


async def list_archived_conversations(
    customer_phone: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 50,
    offset: int = 0
) -> dict[str, Any]:
    """
    List archived conversations with optional filtering.

    Args:
        customer_phone: Filter by customer phone number (E.164 format)
        start_date: Filter conversations created after this date
        end_date: Filter conversations created before this date
        limit: Maximum number of conversations to return
        offset: Number of conversations to skip for pagination

    Returns:
        Dict containing:
        - conversations: list[dict] - List of conversation summaries
        - total_count: int - Total matching conversations
        - has_more: bool - Whether there are more results

    Example:
        >>> result = await list_archived_conversations(
        ...     customer_phone="+34612345678",
        ...     limit=20
        ... )
        >>> print(f"Found {result['total_count']} conversations")
    """
    try:
        from sqlalchemy import func, distinct
        from database.models import Customer

        async for session in get_async_session():
            # Build subquery to get distinct conversation_ids with filtering
            subquery = (
                select(
                    ConversationHistory.conversation_id,
                    func.min(ConversationHistory.timestamp).label("first_message_time"),
                    func.count(ConversationHistory.id).label("message_count"),
                    ConversationHistory.customer_id,
                )
                .group_by(ConversationHistory.conversation_id, ConversationHistory.customer_id)
            )

            # Apply filters
            if customer_phone:
                # Join with Customer to filter by phone
                subquery = (
                    subquery
                    .join(Customer, ConversationHistory.customer_id == Customer.id)
                    .where(Customer.phone == customer_phone)
                )

            if start_date:
                subquery = subquery.having(func.min(ConversationHistory.timestamp) >= start_date)

            if end_date:
                subquery = subquery.having(func.min(ConversationHistory.timestamp) <= end_date)

            subquery = subquery.subquery()

            # Main query with pagination
            stmt = (
                select(
                    subquery.c.conversation_id,
                    subquery.c.first_message_time,
                    subquery.c.message_count,
                    Customer.phone,
                )
                .select_from(subquery)
                .join(Customer, subquery.c.customer_id == Customer.id, isouter=True)
                .order_by(subquery.c.first_message_time.desc())
            )

            # Get total count
            count_result = await session.execute(stmt)
            all_results = count_result.all()
            total_count = len(all_results)

            # Apply pagination
            paginated_results = all_results[offset:offset + limit]
            has_more = (offset + limit) < total_count

            # Format results
            conversations = []
            for row in paginated_results:
                conversations.append({
                    "conversation_id": row.conversation_id,
                    "customer_phone": row.phone,
                    "created_at": row.first_message_time.isoformat() if row.first_message_time else None,
                    "message_count": row.message_count,
                    "has_summary": False,  # Individual message model doesn't track summaries
                })

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
            exc_info=True
        )
        raise
