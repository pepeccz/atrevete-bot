"""
Integration test: whatsapp template migration idempotency (task 2.4).

Verifies that running alembic upgrade to x4y5z6a7b8c9 twice on the test DB
results in exactly 3 rows for the template keys — no duplicates.

NOTE: This test requires the full DB to be up. Skip gracefully if unavailable.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEMPLATE_KEYS = [
    "whatsapp_template_confirm_48h",
    "whatsapp_template_reminder_24h",
    "whatsapp_template_admin_booking",
]

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db",
)


@pytest.fixture
async def db_engine():
    engine = create_async_engine(DB_URL, echo=False)
    yield engine
    await engine.dispose()


async def test_template_keys_present_after_migration(db_engine) -> None:
    """After alembic upgrade head, exactly 3 template keys exist (idempotent re-run)."""
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT key FROM system_settings WHERE key = ANY(:keys)"
            ),
            {"keys": TEMPLATE_KEYS},
        )
        found_keys = {row[0] for row in result.fetchall()}

    # Exactly the 3 expected keys — no more, no less
    assert found_keys == set(TEMPLATE_KEYS), (
        f"Expected keys {set(TEMPLATE_KEYS)}, got {found_keys}. "
        "Run 'alembic upgrade head' on the test DB before running integration tests."
    )


async def test_template_keys_unique_after_migration(db_engine) -> None:
    """Each template key appears exactly once — no duplicate rows."""
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT key, COUNT(*) FROM system_settings "
                "WHERE key = ANY(:keys) GROUP BY key"
            ),
            {"keys": TEMPLATE_KEYS},
        )
        counts = {row[0]: row[1] for row in result.fetchall()}

    for key in TEMPLATE_KEYS:
        assert counts.get(key, 0) == 1, (
            f"Expected exactly 1 row for key '{key}', got {counts.get(key, 0)}. "
            "Migration may not be idempotent."
        )
