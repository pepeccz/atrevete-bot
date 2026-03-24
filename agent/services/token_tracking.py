"""
Atrévete Bot — Token Usage Tracking Service.

Provides atomic token usage recording for LLM calls.
Uses PostgreSQL UPSERT pattern to aggregate monthly totals.
Fire-and-forget: errors are logged, never raised.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database.connection import get_async_session
from database.models import TokenUsage

logger = logging.getLogger(__name__)


async def record_token_usage(input_tokens: int, output_tokens: int) -> None:
    """
    Record token usage for the current month.

    Uses atomic UPSERT to increment counters. If a record for the current
    year/month exists, it increments the values. Otherwise, creates a new record.

    Args:
        input_tokens: Number of input/prompt tokens used
        output_tokens: Number of output/completion tokens used
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return

    now = datetime.now(UTC)
    year = now.year
    month = now.month

    try:
        async with get_async_session() as session:
            # PostgreSQL UPSERT with atomic increment
            stmt = insert(TokenUsage).values(
                id=uuid.uuid4(),
                year=year,
                month=month,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_requests=1,
                created_at=now,
                updated_at=now,
            )

            # On conflict, increment existing values
            stmt = stmt.on_conflict_do_update(
                constraint="uq_token_usage_year_month",
                set_={
                    "input_tokens": TokenUsage.input_tokens + input_tokens,
                    "output_tokens": TokenUsage.output_tokens + output_tokens,
                    "total_requests": TokenUsage.total_requests + 1,
                    "updated_at": now,
                },
            )

            await session.execute(stmt)
            await session.commit()

            logger.debug(
                "Recorded token usage | year=%d month=%d input=%d output=%d",
                year,
                month,
                input_tokens,
                output_tokens,
            )

    except Exception as e:
        # Fire-and-forget: log but never raise — token tracking must not break the agent
        logger.warning("Failed to record token usage: %s", e)


async def get_current_month_usage() -> dict | None:
    """
    Get token usage for the current month.

    Returns:
        Dict with usage data or None if no data exists.
    """
    now = datetime.now(UTC)

    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(TokenUsage).where(
                    TokenUsage.year == now.year,
                    TokenUsage.month == now.month,
                )
            )
            usage = result.scalar_one_or_none()

            if usage:
                return {
                    "year": usage.year,
                    "month": usage.month,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.input_tokens + usage.output_tokens,
                    "total_requests": usage.total_requests,
                }
            return None

    except Exception as e:
        logger.warning("Failed to get current month usage: %s", e)
        return None


async def get_historical_usage(months: int = 12) -> list[dict]:
    """
    Get token usage for the last N months.

    Args:
        months: Number of months to retrieve (max 24).

    Returns:
        List of dicts with usage data, ordered by (year, month) descending.
    """
    months = min(months, 24)

    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(TokenUsage)
                .order_by(TokenUsage.year.desc(), TokenUsage.month.desc())
                .limit(months)
            )
            usage_list = result.scalars().all()

            return [
                {
                    "id": str(u.id),
                    "year": u.year,
                    "month": u.month,
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "total_tokens": u.input_tokens + u.output_tokens,
                    "total_requests": u.total_requests,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "updated_at": u.updated_at.isoformat() if u.updated_at else None,
                }
                for u in usage_list
            ]

    except Exception as e:
        logger.warning("Failed to get historical usage: %s", e)
        return []
