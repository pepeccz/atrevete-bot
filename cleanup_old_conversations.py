#!/usr/bin/env python3
"""
Script to clean up old conversation data from PostgreSQL and Redis.
Keeps only today's conversations (created_at >= today 00:00:00).

Usage:
  python cleanup_old_conversations.py --dry-run    # See what would be deleted
  python cleanup_old_conversations.py              # Actually delete old data
"""

import asyncio
import sys
from datetime import datetime, timezone, date
from typing import List, Set

from shared.config import get_settings
from database.connection import get_async_session
from sqlalchemy import delete, select
from database.models import ConversationHistory, ConversationMessage
import redis.asyncio as redis
from functools import lru_cache
import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_database_url_for_external_use() -> str:
    """Get DATABASE_URL adjusted for external access (outside Docker)"""
    settings = get_settings()
    database_url = settings.DATABASE_URL
    
    # If we're running outside Docker (not in the atrevete network),
    # we need to connect to localhost instead of the service name
    if "@postgres:" in database_url:
        database_url = database_url.replace("@postgres:", "@localhost:")
        logger.info("Adjusted DATABASE_URL for external access: %s", 
                   database_url.split('@')[0] + '@[HIDDEN]')
    
    return database_url


def get_redis_url_for_external_use() -> str:
    """Get REDIS_URL adjusted for external access (outside Docker)"""
    settings = get_settings()
    redis_url = settings.REDIS_URL
    
    # If we're running outside Docker (not in the atrevete network),
    # we need to connect to localhost instead of the service name
    if "@redis:" in redis_url:
        redis_url = redis_url.replace("@redis:", "@localhost:")
        logger.info("Adjusted REDIS_URL for external access: %s", 
                   redis_url.split('@')[0] + '@[HIDDEN]')
    
    return redis_url


@lru_cache
def get_redis_client() -> redis.Redis:
    """Get cached Redis client instance - same pattern as shared/redis_client.py"""
    settings = get_settings()
    
    # Use external URL if needed
    redis_url = get_redis_url_for_external_use()
    
    # Build connection kwargs
    conn_kwargs = {
        "max_connections": 20,
        "decode_responses": True,
        "retry_on_timeout": True,
        "health_check_interval": 30,
    }
    
    # Add password if configured
    if settings.REDIS_PASSWORD:
        conn_kwargs["password"] = settings.REDIS_PASSWORD
    
    return redis.from_url(redis_url, **conn_kwargs)


async def get_today_midnight_utc() -> datetime:
    """Get today's date at 00:00:00 in UTC"""
    today = date.today()
    return datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=timezone.utc)


async def get_today_conversation_ids() -> Set[str]:
    """Get conversation IDs for conversations created today or later"""
    async with get_async_session() as session:
        today_midnight = await get_today_midnight_utc()
        
        # Select conversation IDs where created_at >= today 00:00:00 UTC
        stmt = select(ConversationHistory.conversation_id).where(
            ConversationHistory.created_at >= today_midnight
        )
        result = await session.execute(stmt)
        conversation_ids = {row.conversation_id for row in result.fetchall()}
        
        return conversation_ids


async def cleanup_postgresql(dry_run: bool = False) -> dict:
    """Delete old conversation history and messages from PostgreSQL"""
    stats = {
        "conversations_deleted": 0,
        "messages_deleted": 0,
    }
    
    # Override the database URL for external access if needed
    original_db_url = os.environ.get('DATABASE_URL')
    external_db_url = get_database_url_for_external_use()
    if external_db_url != original_db_url:
        os.environ['DATABASE_URL'] = external_db_url
        # Force reload of settings to pick up the new URL
        from shared.config import get_settings
        get_settings.cache_clear()  # Clear the lru_cache
        settings = get_settings()
    
    async with get_async_session() as session:
        today_midnight = await get_today_midnight_utc()
        
        # First, get counts for reporting
        count_stmt = select(ConversationHistory.id).where(
            ConversationHistory.created_at < today_midnight
        )
        count_result = await session.execute(count_stmt)
        old_conversation_history_ids = [row.id for row in count_result.fetchall()]
        stats["conversations_deleted"] = len(old_conversation_history_ids)
        
        # Get the actual conversation_id strings for these history records
        if old_conversation_history_ids:
            conversation_ids_stmt = select(ConversationHistory.conversation_id).where(
                ConversationHistory.id.in_(old_conversation_history_ids)
            )
            conversation_ids_result = await session.execute(conversation_ids_stmt)
            old_conversation_ids = [row.conversation_id for row in conversation_ids_result.fetchall()]
        else:
            old_conversation_ids = []
        
        if old_conversation_ids:
            # Count messages that will be deleted via CASCADE by joining through conversation_history
            msg_count_stmt = select(ConversationMessage.id).join(
                ConversationHistory, ConversationMessage.conversation_history_id == ConversationHistory.id
            ).where(
                ConversationHistory.conversation_id.in_(old_conversation_ids)
            )
            msg_count_result = await session.execute(msg_count_stmt)
            stats["messages_deleted"] = len(msg_count_result.fetchall())
        
        if not dry_run and old_conversation_ids:
            # Delete old conversations (messages will be deleted via CASCADE)
            delete_stmt = delete(ConversationHistory).where(
                ConversationHistory.created_at < today_midnight
            )
            delete_result = await session.execute(delete_stmt)
            await session.commit()
            
            # Get rowcount from the result - SQLAlchemy 2.0 returns rowcount attribute
            try:
                # In SQLAlchemy 2.0, rowcount might be available via different attributes
                if hasattr(delete_result, 'rowcount'):
                    rowcount = delete_result.rowcount
                elif hasattr(delete_result, '_rowcount'):
                    rowcount = delete_result._rowcount
                else:
                    # Fallback: count the affected rows from the statement
                    rowcount = len(old_conversation_history_ids) if 'old_conversation_history_ids' in locals() else 0
            except AttributeError:
                # Fallback if rowcount attribute doesn't exist
                rowcount = len(old_conversation_history_ids) if 'old_conversation_history_ids' in locals() else 0
            print(f"Deleted {rowcount} conversation histories from PostgreSQL")
        elif dry_run:
            print(f"[DRY RUN] Would delete {stats['conversations_deleted']} conversation histories and "
                  f"{stats['messages_deleted']} messages from PostgreSQL")
    
    return stats


async def cleanup_redis(dry_run: bool = False) -> dict:
    """Delete old conversation-related keys from Redis"""
    stats = {
        "checkpoint_keys_deleted": 0,
        "stream_keys_deleted": 0,
        "other_keys_deleted": 0,
    }
    
    # Get today's conversation IDs
    today_conversation_ids = await get_today_conversation_ids()
    
    redis_client = get_redis_client()
    
    try:
        # Clean up LangGraph checkpoint keys: langgraph:checkpoint:{conversation_id}:{checkpoint_ns}
        checkpoint_pattern = "langgraph:checkpoint:*"
        checkpoint_keys = []
        async for key in redis_client.scan_iter(match=checkpoint_pattern):
            checkpoint_keys.append(key)
        
        # Filter out keys that are NOT from today's conversations
        old_checkpoint_keys = []
        for key in checkpoint_keys:
            # Extract conversation_id from key format: langgraph:checkpoint:{conversation_id}:{checkpoint_ns}
            parts = key.split(":")
            if len(parts) >= 4:
                conversation_id = parts[2]
                if conversation_id not in today_conversation_ids:
                    old_checkpoint_keys.append(key)
            else:
                # Malformed key, treat as old to be safe
                old_checkpoint_keys.append(key)
        
        stats["checkpoint_keys_deleted"] = len(old_checkpoint_keys)
        
        if not dry_run and old_checkpoint_keys:
            # Delete in batches to avoid blocking Redis
            for i in range(0, len(old_checkpoint_keys), 100):
                batch = old_checkpoint_keys[i:i+100]
                if batch:
                    await redis_client.delete(*batch)
            print(f"Deleted {len(old_checkpoint_keys)} LangGraph checkpoint keys from Redis")
        elif dry_run:
            print(f"[DRY RUN] Would delete {len(old_checkpoint_keys)} LangGraph checkpoint keys from Redis")
        
        # Clean up Redis Streams consumer group info (if any)
        # Streams themselves are trimmed automatically, but we can clean consumer groups
        stream_patterns = [
            "incoming_messages_stream",
            "outgoing_messages_stream", 
            "dead_letter_stream"
        ]
        
        # Note: We don't delete streams as they are auto-trimmed, but we can clean up consumer group state
        # For safety in dry-run mode, we'll just report what we would check
        if dry_run:
            print(f"[DRY RUN] Would check Redis Streams for old consumer group state")
        else:
            # In real mode, we could clean up consumer group pending entries, but streams auto-trim
            # So we'll just note that streams are handled by their maxlen configuration
            print("Redis Streams are auto-trimmed via maxlen configuration - no manual cleanup needed")
        
        # Clean up any other conversation-related keys (human mode flags, etc.)
        # Based on redis_client.py comments, we have:
        # - conversation:{conversation_id}:human_mode
        other_patterns = [
            "conversation:*",  # Human mode flags and other conversation metadata
        ]
        
        other_keys_deleted = 0
        for pattern in other_patterns:
            keys = []
            async for key in redis_client.scan_iter(match=pattern):
                # Extract conversation_id if possible
                parts = key.split(":")
                if len(parts) >= 3:
                    # For pattern conversation:{conversation_id}:{suffix}
                    if parts[0] == "conversation" and len(parts) >= 3:
                        conversation_id = parts[1]
                        if conversation_id not in today_conversation_ids:
                            keys.append(key)
                else:
                    # If we can't parse, keep it (don't delete unknown keys)
                    pass
            
            if not dry_run and keys:
                # Delete in batches
                for i in range(0, len(keys), 100):
                    batch = keys[i:i+100]
                    if batch:
                        await redis_client.delete(*batch)
                other_keys_deleted += len(keys)
                print(f"Deleted {len(keys)} keys matching pattern '{pattern}' from Redis")
            elif dry_run:
                print(f"[DRY RUN] Would delete {len(keys)} keys matching pattern '{pattern}' from Redis")
                other_keys_deleted += len(keys)
        
        stats["other_keys_deleted"] = other_keys_deleted
        
    except Exception as e:
        print(f"Error during Redis cleanup: {e}")
        raise
    finally:
        await redis_client.close()
    
    return stats


async def main():
    """Main execution function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Clean up old conversation data")
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true", 
        help="Show detailed output"
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("=== DRY RUN MODE - No data will be deleted ===")
    else:
        print("=== LIVE RUN - Data WILL be deleted ===")
        # Ask for confirmation
        response = input("Are you sure you want to delete old conversation data? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return 1
    
    try:
        # Get settings for logging
        settings = get_settings()
        print(f"Environment: {settings.LOG_LEVEL}")
        print(f"Database: {settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'hidden'}")
        print(f"Redis: {settings.REDIS_URL.split('@')[1] if '@' in settings.REDIS_URL else 'hidden'}")
        print()
        
        # Run cleanup
        print("Starting cleanup process...")
        print()
        
        # PostgreSQL cleanup
        print("1. Cleaning up PostgreSQL...")
        pg_stats = await cleanup_postgresql(dry_run=args.dry_run)
        print()
        
        # Redis cleanup
        print("2. Cleaning up Redis...")
        redis_stats = await cleanup_redis(dry_run=args.dry_run)
        print()
        
        # Summary
        print("=== CLEANUP SUMMARY ===")
        if args.dry_run:
            print("DRY RUN - No data was actually deleted")
        print(f"PostgreSQL:")
        print(f"  - Conversation histories: {pg_stats['conversations_deleted']}")
        print(f"  - Messages: {pg_stats['messages_deleted']}")
        print(f"Redis:")
        print(f"  - LangGraph checkpoint keys: {redis_stats['checkpoint_keys_deleted']}")
        print(f"  - Other conversation keys: {redis_stats['other_keys_deleted']}")
        
        total_deleted = (
            pg_stats['conversations_deleted'] + 
            pg_stats['messages_deleted'] + 
            redis_stats['checkpoint_keys_deleted'] + 
            redis_stats['other_keys_deleted']
        )
        print(f"Total items processed: {total_deleted}")
        
        return 0
        
    except Exception as e:
        print(f"Error during cleanup: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))