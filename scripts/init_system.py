"""
System initialization orchestrator for Atrevete Bot.

This script orchestrates the complete initialization of the system:
- Database migrations via Alembic
- Seed data loading
- Redis index creation
- Verification of all components

Can be run from within Docker containers or standalone.
Designed to be idempotent and safe to run multiple times.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.connection import get_async_session
from sqlalchemy import text
from shared.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def check_database_connection() -> bool:
    """
    Check if database connection is working.

    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        logger.info("Checking database connection...")
        async for session in get_async_session():
            result = await session.execute(text("SELECT 1"))
            result.scalar()
            logger.info("✓ Database connection successful")
            return True
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
        return False


async def check_tables_exist() -> dict[str, bool]:
    """
    Check which critical tables exist in the database.

    Returns:
        dict: Mapping of table names to existence status
    """
    critical_tables = [
        "customers",
        "stylists",
        "services",
        # "packs",  # Removed - packs functionality eliminated
        "appointments",
        # "faqs",  # Removed - FAQs now consolidated in policies table
        "policies",
        "conversation_history",
        "alembic_version"
    ]

    table_status = {}

    try:
        logger.info("Checking table existence...")
        async for session in get_async_session():
            for table in critical_tables:
                query = text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = :table_name
                    )
                """)
                result = await session.execute(query, {"table_name": table})
                exists = result.scalar()
                table_status[table] = exists

                status_icon = "✓" if exists else "✗"
                logger.info(f"  {status_icon} Table '{table}': {'exists' if exists else 'missing'}")

    except Exception as e:
        logger.error(f"Error checking tables: {e}")

    return table_status


async def check_seed_data() -> dict[str, int]:
    """
    Check if seed data exists in critical tables.

    Returns:
        dict: Mapping of table names to row counts
    """
    seed_tables = ["services", "stylists", "policies"]  # "packs" and "faqs" removed
    row_counts = {}

    try:
        logger.info("Checking seed data...")
        async for session in get_async_session():
            for table in seed_tables:
                query = text(f"SELECT COUNT(*) FROM {table}")
                result = await session.execute(query)
                count = result.scalar()
                row_counts[table] = count

                status_icon = "✓" if count > 0 else "⚠"
                logger.info(f"  {status_icon} Table '{table}': {count} rows")

    except Exception as e:
        logger.error(f"Error checking seed data: {e}")

    return row_counts


async def verify_redis_connection() -> bool:
    """
    Verify Redis connection is working.

    Returns:
        bool: True if Redis is accessible, False otherwise
    """
    try:
        logger.info("Checking Redis connection...")
        from shared.redis_client import get_redis_client

        redis_client = get_redis_client()
        await redis_client.ping()
        logger.info("✓ Redis connection successful")
        return True

    except Exception as e:
        logger.error(f"✗ Redis connection failed: {e}")
        return False


async def check_redis_indexes() -> list[str]:
    """
    Check which Redis indexes exist (for RedisSearch/LangGraph).

    Returns:
        list: List of existing index names
    """
    try:
        logger.info("Checking Redis indexes...")
        from shared.redis_client import get_redis_client

        redis_client = get_redis_client()

        # Try to list indexes using FT._LIST command
        try:
            indexes = await redis_client.execute_command("FT._LIST")
            if indexes:
                for idx in indexes:
                    logger.info(f"  ✓ Index exists: {idx}")
                return indexes
            else:
                logger.info("  ⚠ No Redis indexes found")
                return []
        except Exception as e:
            logger.warning(f"  Could not list Redis indexes: {e}")
            return []

    except Exception as e:
        logger.error(f"Error checking Redis indexes: {e}")
        return []


async def run_system_verification() -> bool:
    """
    Run complete system verification.

    Returns:
        bool: True if system is properly initialized, False otherwise
    """
    logger.info("=" * 60)
    logger.info("ATREVETE BOT - SYSTEM VERIFICATION")
    logger.info("=" * 60)

    all_checks_passed = True

    # Check database connection
    if not await check_database_connection():
        all_checks_passed = False
        logger.error("Database connection check failed")

    # Check tables
    table_status = await check_tables_exist()
    if not table_status:
        all_checks_passed = False
        logger.error("Table existence check failed")
    elif not all(table_status.values()):
        all_checks_passed = False
        missing_tables = [t for t, exists in table_status.items() if not exists]
        logger.error(f"Missing tables: {', '.join(missing_tables)}")

    # Check seed data
    row_counts = await check_seed_data()
    if not row_counts:
        all_checks_passed = False
        logger.error("Seed data check failed")
    elif any(count == 0 for count in row_counts.values()):
        empty_tables = [t for t, count in row_counts.items() if count == 0]
        logger.warning(f"Empty seed tables: {', '.join(empty_tables)}")

    # Check Redis connection
    if not await verify_redis_connection():
        all_checks_passed = False
        logger.error("Redis connection check failed")

    # Check Redis indexes (informational only, not critical)
    await check_redis_indexes()

    logger.info("=" * 60)
    if all_checks_passed:
        logger.info("✓ SYSTEM VERIFICATION PASSED")
    else:
        logger.error("✗ SYSTEM VERIFICATION FAILED")
    logger.info("=" * 60)

    return all_checks_passed


async def main():
    """Main entry point for system initialization verification."""
    try:
        success = await run_system_verification()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.exception(f"Fatal error during system verification: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
