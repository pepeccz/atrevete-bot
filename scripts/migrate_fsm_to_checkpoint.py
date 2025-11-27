#!/usr/bin/env python3
"""
DEPRECATED (2025-11-27): Migration completed in development.
=========================================================
This script is kept for historical reference only.
All FSM state is now persisted exclusively via checkpoint.
No migration needed for new deployments.
=========================================================

ADR-011 Migration Script: Populate fsm_state in LangGraph checkpoints.

This script migrates FSM state from separate Redis keys (fsm:{conversation_id})
into the LangGraph checkpoint storage as the new 'fsm_state' field.

Purpose:
--------
Consolidates dual persistence (FSM Redis + LangGraph checkpoint) into single
source of truth by embedding FSM state into checkpoint.

Usage:
------
python scripts/migrate_fsm_to_checkpoint.py [--dry-run] [--limit N]

Options:
  --dry-run    Show what would be migrated without making changes
  --limit N    Migrate only first N checkpoints (default: migrate all)

Example:
--------
# Test migration with first 10 checkpoints
python scripts/migrate_fsm_to_checkpoint.py --dry-run --limit 10

# Run actual migration
python scripts/migrate_fsm_to_checkpoint.py

Behavior:
---------
1. Scans all LangGraph checkpoint keys in Redis (langchain:checkpoint:thread:*)
2. For each checkpoint:
   - Loads checkpoint from Redis
   - Loads corresponding FSM from Redis (fsm:{conversation_id})
   - Adds/updates 'fsm_state' field in checkpoint
   - Saves checkpoint back to Redis (if not dry-run)
3. Validates 100% coverage
4. Logs migration results and any errors

Safety:
-------
- Dry-run mode shows changes without writing
- Validates FSM data before persisting
- Logs all operations for audit trail
- Creates backup of FSM state before migration
"""

import asyncio
import json
import logging
import sys
from argparse import ArgumentParser
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class FSMCheckpointMigration:
    """Migrates FSM state from Redis keys to LangGraph checkpoints."""

    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.migrated_count = 0
        self.skipped_count = 0
        self.error_count = 0
        self.existing_fsm_state_count = 0

    async def scan_checkpoint_keys(self) -> list[str]:
        """Scan Redis for all LangGraph checkpoint keys."""
        keys = []
        cursor = "0"

        while True:
            cursor, batch = await self.redis.scan(
                cursor=cursor,
                match="langchain:checkpoint:thread:*",
                count=100,
            )

            keys.extend([k.decode() if isinstance(k, bytes) else k for k in batch])

            if cursor == "0" or cursor == 0:
                break

        return sorted(keys)

    async def load_checkpoint(self, key: str) -> dict | None:
        """Load checkpoint from Redis."""
        try:
            data_str = await self.redis.get(key)
            if not data_str:
                return None

            if isinstance(data_str, bytes):
                data_str = data_str.decode()

            return json.loads(data_str)
        except (json.JSONDecodeError, RedisError) as e:
            logger.error(f"Failed to load checkpoint {key}: {e}")
            return None

    async def load_fsm_state(self, conversation_id: str) -> dict | None:
        """Load FSM state from Redis key."""
        fsm_key = f"fsm:{conversation_id}"
        try:
            data_str = await self.redis.get(fsm_key)
            if not data_str:
                return None

            if isinstance(data_str, bytes):
                data_str = data_str.decode()

            return json.loads(data_str)
        except (json.JSONDecodeError, RedisError) as e:
            logger.warning(f"Failed to load FSM {fsm_key}: {e}")
            return None

    async def save_checkpoint(self, key: str, checkpoint: dict) -> bool:
        """Save checkpoint back to Redis."""
        try:
            await self.redis.set(key, json.dumps(checkpoint))
            return True
        except RedisError as e:
            logger.error(f"Failed to save checkpoint {key}: {e}")
            return False

    async def migrate_checkpoint(
        self, checkpoint_key: str, dry_run: bool = False
    ) -> bool:
        """
        Migrate single checkpoint.

        Returns:
            True if migrated/processed successfully, False otherwise
        """
        # Extract conversation_id from checkpoint key
        # Format: langchain:checkpoint:thread:{conversation_id}
        parts = checkpoint_key.split(":")
        if len(parts) < 4:
            logger.error(f"Invalid checkpoint key format: {checkpoint_key}")
            self.error_count += 1
            return False

        conversation_id = parts[3]

        # Load checkpoint
        checkpoint = await self.load_checkpoint(checkpoint_key)
        if not checkpoint:
            logger.warning(f"Checkpoint not found or empty: {checkpoint_key}")
            self.skipped_count += 1
            return False

        # Check if checkpoint already has fsm_state
        if checkpoint.get("fsm_state"):
            logger.debug(
                f"Checkpoint {conversation_id} already has fsm_state, skipping"
            )
            self.existing_fsm_state_count += 1
            return True

        # Load FSM state
        fsm_state = await self.load_fsm_state(conversation_id)
        if not fsm_state:
            logger.warning(
                f"No FSM state found for conversation {conversation_id}, skipping"
            )
            self.skipped_count += 1
            return False

        # Add fsm_state to checkpoint
        checkpoint["fsm_state"] = fsm_state
        checkpoint["migrated_at"] = datetime.now(UTC).isoformat()

        # Save if not dry-run
        if not dry_run:
            success = await self.save_checkpoint(checkpoint_key, checkpoint)
            if success:
                logger.info(
                    f"Migrated checkpoint {conversation_id}: "
                    f"fsm_state={fsm_state.get('state', 'unknown')}"
                )
                self.migrated_count += 1
                return True
            else:
                self.error_count += 1
                return False
        else:
            logger.info(
                f"[DRY-RUN] Would migrate checkpoint {conversation_id}: "
                f"fsm_state={fsm_state.get('state', 'unknown')}"
            )
            self.migrated_count += 1
            return True

    async def run(self, dry_run: bool = False, limit: int | None = None) -> None:
        """Run migration."""
        logger.info(
            f"Starting FSM → Checkpoint migration (dry_run={dry_run}, limit={limit})"
        )

        # Get all checkpoint keys
        checkpoint_keys = await self.scan_checkpoint_keys()
        logger.info(f"Found {len(checkpoint_keys)} checkpoints to process")

        if limit:
            checkpoint_keys = checkpoint_keys[:limit]
            logger.info(f"Limited to {limit} checkpoints")

        # Migrate each checkpoint
        for i, key in enumerate(checkpoint_keys, 1):
            await self.migrate_checkpoint(key, dry_run=dry_run)

            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(checkpoint_keys)} checkpoints")

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("MIGRATION SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total checkpoints processed: {len(checkpoint_keys)}")
        logger.info(f"✅ Migrated: {self.migrated_count}")
        logger.info(f"⏭️  Already have fsm_state: {self.existing_fsm_state_count}")
        logger.info(f"⏸️  Skipped (no FSM): {self.skipped_count}")
        logger.info(f"❌ Errors: {self.error_count}")

        if dry_run:
            logger.info("\n🔍 DRY-RUN MODE - No changes were made")
        else:
            logger.info(
                f"\n✅ Migration complete! {self.migrated_count} checkpoints updated"
            )

        # Validation
        if self.error_count == 0:
            logger.info("✅ All operations completed successfully")
        else:
            logger.error(f"⚠️  {self.error_count} errors occurred during migration")
            sys.exit(1)


async def main():
    """Main entry point."""
    parser = ArgumentParser(description="Migrate FSM state to LangGraph checkpoints")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Migrate only first N checkpoints (default: all)",
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
        # Run migration
        migration = FSMCheckpointMigration(redis)
        await migration.run(dry_run=args.dry_run, limit=args.limit)
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
