"""
API routes for conversation history management.

This module provides REST endpoints for retrieving archived conversations
from PostgreSQL (conversations older than 24 hours).
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.routes.admin import get_current_user
from shared.archive_retrieval import (
    get_archived_conversation,
    list_archived_conversations,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/{conversation_id}/history")
async def get_conversation_history(
    conversation_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Retrieve archived conversation messages from PostgreSQL.

    This endpoint fetches messages for conversations older than 24 hours
    that have been archived from Redis to PostgreSQL.

    **Parameters:**
    - **conversation_id**: Unique conversation identifier (thread_id)
    - **limit**: Maximum number of messages to return (1-500, default: 100)
    - **offset**: Number of messages to skip for pagination (default: 0)

    **Returns:**
    ```json
    {
        "conversation_id": "wa-msg-123",
        "customer_phone": "+34612345678",
        "messages": [
            {
                "role": "user",
                "content": "Hola",
                "timestamp": "2025-10-29T10:00:00+01:00"
            },
            {
                "role": "assistant",
                "content": "¡Hola! Bienvenido...",
                "timestamp": "2025-10-29T10:00:05+01:00"
            }
        ],
        "total_messages": 25,
        "has_more": false
    }
    ```

    **Errors:**
    - **404**: Conversation not found in archive
    - **500**: Internal server error
    """
    try:
        result = await get_archived_conversation(
            conversation_id=conversation_id,
            limit=limit,
            offset=offset
        )

        if result["total_messages"] == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation {conversation_id} not found in archive"
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error retrieving conversation history for {conversation_id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error retrieving conversation history"
        )


@router.get("/")
async def list_conversations(
    current_user: Annotated[dict, Depends(get_current_user)],
    customer_phone: Annotated[str | None, Query()] = None,
    start_date: Annotated[datetime | None, Query()] = None,
    end_date: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    List archived conversations with optional filtering.

    Retrieve a paginated list of archived conversations with optional
    filters by customer phone, date range, etc.

    **Parameters:**
    - **customer_phone**: Filter by customer phone (E.164 format, e.g., +34612345678)
    - **start_date**: Filter conversations created after this date (ISO 8601)
    - **end_date**: Filter conversations created before this date (ISO 8601)
    - **limit**: Maximum conversations to return (1-100, default: 50)
    - **offset**: Number of conversations to skip (default: 0)

    **Returns:**
    ```json
    {
        "conversations": [
            {
                "conversation_id": "wa-msg-123",
                "customer_phone": "+34612345678",
                "created_at": "2025-10-29T10:00:00+01:00",
                "message_count": 25,
                "has_summary": true
            }
        ],
        "total_count": 150,
        "has_more": true
    }
    ```

    **Example Requests:**
    - `GET /conversations/` - List all archived conversations
    - `GET /conversations/?customer_phone=%2B34612345678` - Filter by phone
    - `GET /conversations/?start_date=2025-10-01T00:00:00Z&limit=20` - Filter by date

    **Errors:**
    - **500**: Internal server error
    """
    try:
        result = await list_archived_conversations(
            customer_phone=customer_phone,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )

        return result

    except Exception as e:
        logger.error(
            f"Error listing archived conversations: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error listing conversations"
        )
