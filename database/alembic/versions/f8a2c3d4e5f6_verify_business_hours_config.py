"""verify and auto-correct business hours configuration

Revision ID: f8a2c3d4e5f6
Revises: 62769e850a51
Create Date: 2025-11-26 10:30:00.000000

"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'f8a2c3d4e5f6'
down_revision: Union[str, None] = '62769e850a51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Configure logging
logger = logging.getLogger('alembic.runtime.migration')

# Expected business hours configuration
# Format: (day_of_week, is_closed, start_hour, start_minute, end_hour, end_minute)
EXPECTED_CONFIG = [
    (0, True, None, 0, None, 0),     # Monday: CLOSED
    (1, False, 10, 0, 20, 0),         # Tuesday: 10:00-20:00
    (2, False, 10, 0, 20, 0),         # Wednesday: 10:00-20:00
    (3, False, 10, 0, 20, 0),         # Thursday: 10:00-20:00
    (4, False, 10, 0, 20, 0),         # Friday: 10:00-20:00
    (5, False, 9, 0, 14, 0),          # Saturday: 9:00-14:00
    (6, True, None, 0, None, 0),     # Sunday: CLOSED
]

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def upgrade() -> None:
    """
    Verify and auto-correct business_hours configuration.

    This migration ensures the business_hours table contains the correct
    configuration as single source of truth for all availability checks.

    Expected configuration:
    - Monday: CLOSED
    - Tuesday-Friday: 10:00-20:00
    - Saturday: 9:00-14:00
    - Sunday: CLOSED

    The migration is idempotent and safe to run multiple times.
    """
    connection = op.get_bind()

    logger.info("=" * 80)
    logger.info("BUSINESS HOURS CONFIGURATION VERIFICATION")
    logger.info("=" * 80)

    corrections_made = 0
    verified_count = 0

    for day_of_week, expected_closed, expected_start_h, expected_start_m, expected_end_h, expected_end_m in EXPECTED_CONFIG:
        day_name = DAY_NAMES[day_of_week]

        # Fetch current configuration
        result = connection.execute(
            text("""
                SELECT is_closed, start_hour, start_minute, end_hour, end_minute
                FROM business_hours
                WHERE day_of_week = :day
            """),
            {"day": day_of_week}
        ).fetchone()

        if result is None:
            # Missing row - insert it
            logger.warning(f"⚠️  {day_name}: Missing configuration - INSERTING")
            connection.execute(
                text("""
                    INSERT INTO business_hours (id, day_of_week, is_closed, start_hour, start_minute, end_hour, end_minute)
                    VALUES (gen_random_uuid(), :day, :closed, :start_h, :start_m, :end_h, :end_m)
                """),
                {
                    "day": day_of_week,
                    "closed": expected_closed,
                    "start_h": expected_start_h,
                    "start_m": expected_start_m,
                    "end_h": expected_end_h,
                    "end_m": expected_end_m,
                }
            )
            corrections_made += 1
            logger.info(f"   ✅ {day_name}: Configuration INSERTED")
            continue

        current_closed, current_start_h, current_start_m, current_end_h, current_end_m = result

        # Check if current matches expected
        mismatch = False
        errors = []

        if current_closed != expected_closed:
            mismatch = True
            errors.append(f"is_closed={current_closed} (expected {expected_closed})")

        if current_start_h != expected_start_h:
            mismatch = True
            errors.append(f"start_hour={current_start_h} (expected {expected_start_h})")

        if current_start_m != expected_start_m:
            mismatch = True
            errors.append(f"start_minute={current_start_m} (expected {expected_start_m})")

        if current_end_h != expected_end_h:
            mismatch = True
            errors.append(f"end_hour={current_end_h} (expected {expected_end_h})")

        if current_end_m != expected_end_m:
            mismatch = True
            errors.append(f"end_minute={current_end_m} (expected {expected_end_m})")

        if mismatch:
            logger.warning(f"⚠️  {day_name}: MISMATCH DETECTED")
            for error in errors:
                logger.warning(f"     - {error}")

            # Auto-correct
            connection.execute(
                text("""
                    UPDATE business_hours
                    SET is_closed = :closed,
                        start_hour = :start_h,
                        start_minute = :start_m,
                        end_hour = :end_h,
                        end_minute = :end_m
                    WHERE day_of_week = :day
                """),
                {
                    "day": day_of_week,
                    "closed": expected_closed,
                    "start_h": expected_start_h,
                    "start_m": expected_start_m,
                    "end_h": expected_end_h,
                    "end_m": expected_end_m,
                }
            )
            corrections_made += 1
            logger.info(f"   ✅ {day_name}: Configuration CORRECTED")
        else:
            verified_count += 1
            status = "CLOSED" if expected_closed else f"{expected_start_h:02d}:{expected_start_m:02d}-{expected_end_h:02d}:{expected_end_m:02d}"
            logger.info(f"✅ {day_name}: {status} - VERIFIED")

    logger.info("=" * 80)
    if corrections_made > 0:
        logger.warning(f"⚠️  CORRECTIONS MADE: {corrections_made} day(s) updated")
    logger.info(f"✅ VERIFICATION COMPLETE: {verified_count} day(s) already correct")
    logger.info("=" * 80)


def downgrade() -> None:
    """
    No downgrade needed - this migration only verifies/corrects data.

    The business_hours table structure remains unchanged.
    Reverting data changes would be unsafe as it could restore incorrect values.
    """
    logger.info("No downgrade needed - data verification migration")
    pass
