#!/usr/bin/env python3
"""
One-shot script to archive test conversations immediately.

This script bypasses the 23-hour cutoff and archives specified conversations
from Redis to PostgreSQL for testing purposes.

Usage:
    # Archive all conversations
    ./venv/bin/python scripts/archive_now.py

    # Archive specific conversation
    ./venv/bin/python scripts/archive_now.py 7777
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import redis
from sqlalchemy import select, func

# Add project root to path
sys.path.insert(0, '/home/pepe/atrevete-bot')

from database.connection import get_async_session
from database.models import ConversationHistory, MessageRole
from shared.config import get_settings

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Madrid")


def get_redis_client():
    """Get synchronous Redis client."""
    settings = get_settings()
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=False,
        retry_on_timeout=True,
    )


async def find_all_checkpoints(redis_client, filter_conversation_id: str | None = None):
    """Find all checkpoint keys, optionally filtered by conversation ID."""
    keys = list(redis_client.scan_iter(match="langgraph:checkpoint:*", count=1000))
    logger.info(f"Found {len(keys)} total checkpoint keys in Redis")

    checkpoints = []
    for key in keys:
        key_str = key.decode('utf-8') if isinstance(key, bytes) else key

        # Extract conversation_id from key
        # Format: langgraph:checkpoint:{thread_id}:{checkpoint_ns}
        parts = key_str.split(":")
        if len(parts) >= 4:
            conversation_id = parts[2]

            # Apply filter if specified
            if filter_conversation_id and conversation_id != filter_conversation_id:
                continue

            checkpoints.append((key_str, conversation_id))
            logger.debug(f"Found checkpoint: {key_str} -> conversation_id={conversation_id}")

    return checkpoints


async def get_checkpoint_data(redis_client, key: str) -> dict | None:
    """Retrieve and parse checkpoint data."""
    try:
        # Try JSON.GET first (RedisJSON)
        try:
            data = redis_client.execute_command('JSON.GET', key, '.')
            if data:
                if isinstance(data, bytes):
                    data = data.decode('utf-8')
                return json.loads(data)
        except Exception:
            pass

        # Fall back to GET (binary)
        data = redis_client.get(key)
        if data is None:
            return None

        if isinstance(data, bytes):
            data = data.decode('utf-8')
        return json.loads(data)

    except Exception as e:
        logger.error(f"Error parsing checkpoint {key}: {e}")
        return None


async def extract_messages_from_checkpoint(checkpoint: dict) -> list[dict]:
    """Extract messages from LangGraph checkpoint structure."""
    messages = []

    # Navigate LangGraph checkpoint structure
    # Structure: {"channel_values": {"messages": [...]}, "channel_versions": {...}}
    channel_values = checkpoint.get('channel_values', {})

    if isinstance(channel_values, dict):
        raw_messages = channel_values.get('messages', [])
        conversation_id = channel_values.get('conversation_id')
        customer_id = channel_values.get('customer_id')
        summary = channel_values.get('conversation_summary')

        logger.info(f"Found {len(raw_messages)} messages in checkpoint")
        if summary:
            logger.info(f"Found conversation summary: {summary[:100]}...")

        return {
            'conversation_id': conversation_id,
            'customer_id': customer_id,
            'messages': raw_messages,
            'summary': summary,
        }

    return None


async def archive_to_db(data: dict) -> int:
    """Insert conversation data into PostgreSQL."""
    conversation_id = data.get('conversation_id')
    customer_id = data.get('customer_id')
    messages = data.get('messages', [])
    summary = data.get('summary')

    if not conversation_id:
        logger.warning("No conversation_id found, skipping")
        return 0

    inserted = 0

    async with get_async_session() as session:
        # Check if already archived
        existing = await session.execute(
            select(func.count()).select_from(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        existing_count = existing.scalar()

        if existing_count > 0:
            logger.info(f"Conversation {conversation_id} already has {existing_count} messages in DB")
            return 0

        # Insert messages
        for msg in messages:
            try:
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                timestamp_str = msg.get('timestamp')

                # Parse timestamp
                if timestamp_str:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str)
                        if timestamp.tzinfo is None:
                            timestamp = timestamp.replace(tzinfo=TIMEZONE)
                    except Exception:
                        timestamp = datetime.now(TIMEZONE)
                else:
                    timestamp = datetime.now(TIMEZONE)

                # Map role
                try:
                    message_role = MessageRole[role.upper()]
                except (KeyError, AttributeError):
                    message_role = MessageRole.USER

                record = ConversationHistory(
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    timestamp=timestamp,
                    message_role=message_role,
                    message_content=content,
                    metadata_={},
                )
                session.add(record)
                inserted += 1

            except Exception as e:
                logger.error(f"Error inserting message: {e}")

        # Insert summary as system message
        if summary:
            try:
                record = ConversationHistory(
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    timestamp=datetime.now(TIMEZONE),
                    message_role=MessageRole.SYSTEM,
                    message_content=summary,
                    metadata_={'type': 'conversation_summary'},
                )
                session.add(record)
                inserted += 1
                logger.info(f"Inserted conversation summary")
            except Exception as e:
                logger.error(f"Error inserting summary: {e}")

        await session.commit()

    logger.info(f"Inserted {inserted} records for conversation {conversation_id}")
    return inserted


async def main(filter_conversation_id: str | None = None):
    """Main archival function."""
    logger.info("=" * 60)
    logger.info("ONE-SHOT ARCHIVAL SCRIPT")
    logger.info("=" * 60)

    if filter_conversation_id:
        logger.info(f"Filtering for conversation: {filter_conversation_id}")
    else:
        logger.info("Archiving ALL conversations")

    redis_client = get_redis_client()

    # Find checkpoints
    checkpoints = await find_all_checkpoints(redis_client, filter_conversation_id)
    logger.info(f"Found {len(checkpoints)} checkpoints to process")

    if not checkpoints:
        logger.info("No checkpoints found to archive")
        return

    total_inserted = 0

    for key, conversation_id in checkpoints:
        logger.info(f"\n--- Processing conversation {conversation_id} ---")

        # Get checkpoint data
        checkpoint = await get_checkpoint_data(redis_client, key)
        if not checkpoint:
            logger.warning(f"Could not parse checkpoint {key}")
            continue

        # Extract messages
        data = await extract_messages_from_checkpoint(checkpoint)
        if not data:
            logger.warning(f"No messages found in checkpoint {key}")
            continue

        # Archive to DB
        inserted = await archive_to_db(data)
        total_inserted += inserted

    logger.info(f"\n{'=' * 60}")
    logger.info(f"ARCHIVAL COMPLETE: {total_inserted} total records inserted")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    # Get conversation ID from command line if provided
    conversation_id = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(conversation_id))
