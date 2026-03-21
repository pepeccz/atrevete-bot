#!/usr/bin/env python3
"""
Simple script to clean up old conversations from database and Redis.
Uses direct connection parameters instead of trying to reuse application settings.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, date

# Add the project root to the path so we can import from shared/
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import asyncpg
import redis.asyncio as redis
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Connection parameters - match those in .env
DB_CONFIG = {
    'user': 'atrevete',
    'password': 'a3f7c2e9d1b8f4a6c5e2d9b3f8a1c4e7',
    'database': 'atrevete_db',
    'host': 'localhost',  # Using localhost instead of postgres service name
    'port': 5432,
}

REDIS_CONFIG = {
    'host': 'localhost',
    'port': 6379,
    'password': '9c8dc04af94f95a92896d42d030be7868f60fd5b04aa82d26ae5e9397b7e8eda',
    'decode_responses': True,
}


def get_today_start() -> datetime:
    """Get today's date at 00:00:00 in UTC."""
    today = date.today()
    return datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=timezone.utc)


async def cleanup_postgresql(dry_run: bool = False) -> dict:
    """Delete old conversation history and messages from PostgreSQL"""
    stats = {
        "conversations_deleted": 0,
        "messages_deleted": 0,
    }
    
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        today_start = get_today_start()
        
        # First, get counts for reporting
        count_query = '''
            SELECT COUNT(*) 
            FROM conversation_history 
            WHERE created_at < $1
        '''
        conversations_to_delete = await conn.fetchval(count_query, today_start)
        stats["conversations_deleted"] = conversations_to_delete
        
        # Count messages that will be deleted via CASCADE
        messages_count_query = '''
            SELECT COUNT(*) 
            FROM conversation_messages cm
            JOIN conversation_history ch ON cm.conversation_history_id = ch.id
            WHERE ch.created_at < $1
        '''
        messages_to_delete = await conn.fetchval(messages_count_query, today_start)
        stats["messages_deleted"] = messages_to_delete
        
        print(f"Found {conversations_to_delete} conversations and {messages_to_delete} messages to delete")
        
        if dry_run:
            await conn.close()
            return stats
        
        # Actually delete the conversations (CASCADE will delete messages)
        delete_query = '''
            DELETE FROM conversation_history 
            WHERE created_at < $1
        '''
        delete_result = await conn.execute(delete_query, today_start)
        
        # Parse the result to get row count (format: "DELETE N")
        deleted_count = int(delete_result.split()[1])
        print(f"Deleted {deleted_count} conversation histories from PostgreSQL")
        
        await conn.close()
        return stats
        
    except Exception as e:
        await conn.close()
        raise e


async def cleanup_redis(dry_run: bool = False) -> dict:
    """Delete old conversation-related keys from Redis"""
    stats = {
        "checkpoint_keys_deleted": 0,
        "other_keys_deleted": 0,
    }
    
    # Get today's conversation IDs from database
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        today_start = get_today_start()
        
        # Get conversation IDs from today
        query = '''
            SELECT conversation_id 
            FROM conversation_history 
            WHERE created_at >= $1
        '''
        today_conversation_ids = {row['conversation_id'] for row in await conn.fetch(query, today_start)}
        
        await conn.close()
        
        print(f"Found {len(today_conversation_ids)} conversation IDs from today to preserve")
        
    except Exception as e:
        await conn.close()
        raise e
    
    # Connect to Redis
    redis_client = redis.Redis(**REDIS_CONFIG)
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
        
        # Clean up any other conversation-related keys (human mode flags, etc.)
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
        
        await redis_client.close()
        return stats
        
    except Exception as e:
        await redis_client.close()
        raise e


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
        "--skip-redis", 
        action="store_true", 
        help="Skip Redis cleanup"
    )
    parser.add_argument(
        "--skip-db", 
        action="store_true", 
        help="Skip database cleanup"
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
        # Run cleanup
        print("Starting cleanup process...")
        print()
        
        # PostgreSQL cleanup
        if not args.skip_db:
            print("1. Cleaning up PostgreSQL...")
            pg_stats = await cleanup_postgresql(dry_run=args.dry_run)
            print()
        
        # Redis cleanup
        if not args.skip_redis:
            print("2. Cleaning up Redis...")
            redis_stats = await cleanup_redis(dry_run=args.dry_run)
            print()
        
        # Summary
        print("=== CLEANUP SUMMARY ===")
        if args.dry_run:
            print("DRY RUN - No data was actually deleted")
        if not args.skip_db:
            print(f"PostgreSQL:")
            print(f"  - Conversation histories: {pg_stats['conversations_deleted']}")
            print(f"  - Messages: {pg_stats['messages_deleted']}")
        if not args.skip_redis:
            print(f"Redis:")
            print(f"  - LangGraph checkpoint keys: {redis_stats['checkpoint_keys_deleted']}")
            print(f"  - Other conversation keys: {redis_stats['other_keys_deleted']}")
        
        total_deleted = 0
        if not args.skip_db:
            total_deleted += pg_stats['conversations_deleted'] + pg_stats['messages_deleted']
        if not args.skip_redis:
            total_deleted += redis_stats['checkpoint_keys_deleted'] + redis_stats['other_keys_deleted']
        print(f"Total items processed: {total_deleted}")
        
        return 0
        
    except Exception as e:
        print(f"Error during cleanup: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))