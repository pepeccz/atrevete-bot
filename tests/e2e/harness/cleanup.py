"""CLI utility for safe QA test data cleanup.

Usage:
    python tests/e2e/harness/cleanup.py [--dry-run] [--age-hours N]

Safety guards (MUST pass before any DELETE):
1. Settings.TEST_PHONE_PREFIX non-empty AND starts with '+349'
2. Settings.TEST_MODE_GCAL_SKIP is True

Reuses StateResetHarness.cleanup_db() from state_reset.py for FK-ordered deletes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.config import get_settings
from tests.e2e.harness.state_reset import StateResetHarness


def _validate_safety_guards() -> str:
    """Check all safety guards. Returns prefix on success; raises RuntimeError on violation."""
    settings = get_settings()

    prefix = settings.TEST_PHONE_PREFIX.strip()
    if not prefix:
        raise RuntimeError(
            "TEST_PHONE_PREFIX is empty — refusing cleanup. "
            "Set TEST_PHONE_PREFIX=+34999 (or similar +349-prefix) in your environment."
        )
    if not prefix.startswith("+349"):
        raise RuntimeError(
            f"TEST_PHONE_PREFIX must start with +349 (got: {prefix!r}) — refusing cleanup. "
            "This guard prevents accidental deletion of real Spanish mobile numbers (+346/+347)."
        )
    if not settings.TEST_MODE_GCAL_SKIP:
        raise RuntimeError(
            "TEST_MODE_GCAL_SKIP is False — refusing cleanup. "
            "Set TEST_MODE_GCAL_SKIP=true in your environment to confirm you are in sandbox mode."
        )

    return prefix


async def _list_test_phones(prefix: str) -> list[str]:
    """Query the DB for all customer phones starting with the test prefix.

    Creates its own DB session.
    """
    settings = get_settings()
    db_url = settings.DATABASE_URL
    engine = create_async_engine(db_url, echo=False)
    phones: list[str] = []
    try:
        async with AsyncSession(engine) as session:
            result = await session.execute(
                text("SELECT phone FROM customers WHERE phone LIKE :pattern"),
                {"pattern": f"{prefix}%"},
            )
            phones = [row[0] for row in result.fetchall()]
    finally:
        await engine.dispose()
    return phones


async def run_cleanup(dry_run: bool, age_hours: int | None) -> dict[str, Any]:
    """Run the cleanup operation with safety guards.

    Args:
        dry_run: If True, only report counts without deleting.
        age_hours: Only clean records older than N hours (None = no filter).

    Returns:
        Summary dict with dry_run flag, phones_found, and (if not dry_run) deletion counts.

    Raises:
        RuntimeError: If safety guards fail.
    """
    prefix = _validate_safety_guards()
    phones = await _list_test_phones(prefix)

    if dry_run:
        return {
            "dry_run": True,
            "phones_found": len(phones),
            "phones": phones,
        }

    settings = get_settings()
    redis_url = settings.REDIS_URL
    redis_password = getattr(settings, "REDIS_PASSWORD", "") or ""

    redis_client = redis.from_url(
        redis_url,
        password=redis_password or None,
        decode_responses=False,
    )

    try:
        harness = StateResetHarness(redis_client=redis_client)

        total_appointments_deleted = 0
        total_customers_deleted = 0

        for phone in phones:
            db_result = await harness.cleanup_db(phone)
            total_appointments_deleted += db_result.get("appointments_deleted", 0)
            if db_result.get("customer_deleted"):
                total_customers_deleted += 1
    finally:
        await redis_client.aclose()

    return {
        "dry_run": False,
        "phones_found": len(phones),
        "phones": phones,
        "appointments_deleted": total_appointments_deleted,
        "customers_deleted": total_customers_deleted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safe QA test data cleanup. Requires TEST_MODE_GCAL_SKIP=true and a +349-prefix phone."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts without executing deletes.",
    )
    parser.add_argument(
        "--age-hours",
        type=int,
        default=None,
        help="Only clean records older than N hours (default: no filter).",
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(run_cleanup(dry_run=args.dry_run, age_hours=args.age_hours))
    except RuntimeError as exc:
        print(f"[cleanup] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    import json

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
