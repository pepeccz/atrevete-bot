#!/usr/bin/env python3
"""
ADR-011 Cleanup Script: Remove fsm:* Redis keys after checkpoint migration.

This script cleans up the separate FSM Redis keys (fsm:{conversation_id}) after
all FSM state has been migrated into LangGraph checkpoints.

Purpose:
--------
Eliminates dual persistence by removing the separate FSM Redis keys, leaving
only the single source of truth (LangGraph checkpoints).

Usage:
------
python scripts/cleanup_fsm_redis_keys.py [--dry-run] [--keep-for-days N]

Options:
  --dry-run         Show what would be deleted without making changes
  --keep-for-days N Keep keys for N days before deletion (default: 0, delete immediately)

Example:
--------
# Preview what would be deleted
python scripts/cleanup_fsm_redis_keys.py --dry-run

# Delete only keys older than 7 days (safety margin)
python scripts/cleanup_fsm_redis_keys.py --keep-for-days 7

# Delete all FSM keys immediately
python scripts/cleanup_fsm_redis_keys.py

Safety:
-------
- Dry-run mode shows deletions without executing
- Optional TTL safety check keeps recent keys
- Validates checkpoint has fsm_state before deleting FSM key
- Logs all deletions for audit trail
- Skips keys that don't have matching checkpoints
"""

import asyncio
import json
import logging
import sys
from argparse import ArgumentParser
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class FSMKeyCleanup:
    """Removes fsm:* Redis keys after checkpoint migration."""

    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.deleted_count = 0
        self.skipped_count = 0
        self.error_count = 0
        self.protected_count = 0

    async def scan_fsm_keys(self) -> list[str]:
        """Scan Redis for all FSM keys."""
        keys = []
        cursor = "0"

        while True:
            cursor, batch = await self.redis.scan(
                cursor=cursor,
                match="fsm:*",
                count=100,
            )

            keys.extend([k.decode() if isinstance(k, bytes) else k for k in batch])

            if cursor == "0" or cursor == 0:
                break

        return sorted(keys)

    async def get_checkpoint_key(self, conversation_id: str) -> str:
        """Get checkpoint key for conversation."""
        return f"langchain:checkpoint:thread:{conversation_id}"

    async def checkpoint_has_fsm_state(self, conversation_id: str) -> bool:
        """Check if checkpoint has fsm_state field."""
        checkpoint_key = await self.get_checkpoint_key(conversation_id)

        try:
            data_str = await self.redis.get(checkpoint_key)
            if not data_str:
                return False

            if isinstance(data_str, bytes):
                data_str = data_str.decode()

            checkpoint = json.loads(data_str)
            return "fsm_state" in checkpoint
        except (json.JSONDecodeError, RedisError):
            return False

    async def get_key_ttl(self, key: str) -> int | None:
        """Get remaining TTL of a key in seconds."""
        try:
            ttl = await self.redis.ttl(key)
            return ttl if ttl >= 0 else None
        except RedisError:
            return None

    async def should_keep_key(
        self, key: str, keep_for_days: int = 0
    ) -> bool:
        """Check if key should be kept based on TTL."""
        if keep_for_days == 0:
            return False

        ttl = await self.get_key_ttl(key)
        if ttl is None:
            # No TTL set - keep it (error on the side of caution)
            return True

        # Keep if TTL is newer than keep_for_days
        seconds_to_keep = keep_for_days * 86400
        return ttl > seconds_to_keep

    async def delete_fsm_key(
        self, fsm_key: str, dry_run: bool = False, keep_for_days: int = 0
    ) -> bool:
        """
        Delete FSM key safely.

        Returns:
            True if deleted/processed successfully, False otherwise
        """
        # Extract conversation_id from fsm key
        # Format: fsm:{conversation_id}
        conversation_id = fsm_key[4:]  # Remove 'fsm:' prefix

        # Check if checkpoint has fsm_state
        has_fsm_state = await self.checkpoint_has_fsm_state(conversation_id)
        if not has_fsm_state:
            logger.warning(
                f"Checkpoint {conversation_id} missing fsm_state, keeping key as backup"
            )
            self.skipped_count += 1
            return False

        # Check TTL protection
        if await self.should_keep_key(fsm_key, keep_for_days=keep_for_days):
            logger.debug(
                f"Key {fsm_key} protected by TTL safety margin ({keep_for_days} days)"
            )
            self.protected_count += 1
            return False

        # Delete if not dry-run
        if not dry_run:
            try:
                await self.redis.delete(fsm_key)
                logger.info(f"Deleted FSM key: {fsm_key}")
                self.deleted_count += 1
                return True
            except RedisError as e:
                logger.error(f"Failed to delete {fsm_key}: {e}")
                self.error_count += 1
                return False
        else:
            logger.info(f"[DRY-RUN] Would delete FSM key: {fsm_key}")
            self.deleted_count += 1
            return True

    async def run(
        self, dry_run: bool = False, keep_for_days: int = 0
    ) -> None:
        """Run cleanup."""
        logger.info(
            f"Starting FSM key cleanup (dry_run={dry_run}, keep_for_days={keep_for_days})"
        )

        # Get all FSM keys
        fsm_keys = await self.scan_fsm_keys()
        logger.info(f"Found {len(fsm_keys)} FSM keys to process")

        # Delete each key
        for i, key in enumerate(fsm_keys, 1):
            await self.delete_fsm_key(key, dry_run=dry_run, keep_for_days=keep_for_days)

            if i % 100 == 0:
                logger.info(f"Progress: {i}/{len(fsm_keys)} keys")

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("CLEANUP SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total FSM keys processed: {len(fsm_keys)}")
        logger.info(f"✅ Deleted: {self.deleted_count}")
        logger.info(f"⏸️  Skipped (no checkpoint fsm_state): {self.skipped_count}")
        logger.info(f"🔒 Protected (TTL safety): {self.protected_count}")
        logger.info(f"❌ Errors: {self.error_count}")

        if dry_run:
            logger.info("\n🔍 DRY-RUN MODE - No deletions were made")
        else:
            logger.info(f"\n✅ Cleanup complete! {self.deleted_count} keys deleted")

        # Validation
        if self.error_count == 0:
            logger.info("✅ All operations completed successfully")
        else:
            logger.error(f"⚠️  {self.error_count} errors occurred during cleanup")
            sys.exit(1)


async def main():
    """Main entry point."""
    parser = ArgumentParser(
        description="Clean up FSM Redis keys after checkpoint migration"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without making changes",
    )
    parser.add_argument(
        "--keep-for-days",
        type=int,
        default=0,
        help="Keep keys for N days before deletion (default: 0, delete immediately)",
    )

    args = parser.parse_args()

    # Connect to Redis
    try:
        redis = Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=False,  # Handle bytes manually
        )

        # Test connection
        await redis.ping()
        logger.info("Connected to Redis")
    except RedisError as e:
        logger.error(f"Failed to connect to Redis: {e}")
        sys.exit(1)

    try:
        # Run cleanup
        cleanup = FSMKeyCleanup(redis)
        await cleanup.run(dry_run=args.dry_run, keep_for_days=args.keep_for_days)
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
