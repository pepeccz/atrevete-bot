"""Integration test: final_warning_sent_at migration idempotency (T5 — RED before T6).

Tests three scenarios for migration f1a2b3c4d5e6:
  1. After alembic upgrade to f1a2b3c4d5e6: column final_warning_sent_at exists on appointments.
  2. After alembic downgrade -1: column is absent.
  3. Second alembic upgrade f1a2b3c4d5e6: column re-appears (idempotency, CC-R4).

Skips gracefully when Postgres is not reachable (CI without DB service).

RED contract: fails BEFORE T6 creates the migration file, because the revision
              f1a2b3c4d5e6 does not yet exist in database/alembic/versions/.
GREEN contract: passes AFTER T6 is applied.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_REVISION = "f1a2b3c4d5e6"
PARENT_REVISION = "e1f2a3b4c5d6"
TARGET_TABLE = "appointments"
TARGET_COLUMN = "final_warning_sent_at"

# Resolve DATABASE_URL — accepts both asyncpg (app) and psycopg (alembic) forms.
# The integration-test env uses asyncpg; alembic subprocess needs psycopg.
_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db",
)
# Alembic sync URL — swap driver for subprocess calls
_SYNC_DB_URL = _ASYNC_DB_URL.replace(
    "postgresql+asyncpg://", "postgresql+psycopg://"
).replace(
    "postgresql+asyncpg+pg8000://", "postgresql+psycopg://"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _postgres_reachable() -> bool:
    """Return True if Postgres is reachable on localhost:5432."""
    try:
        s = socket.create_connection(("localhost", 5432), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _skip_if_no_postgres() -> None:
    """Skip the test if Postgres is not reachable."""
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable — skipping migration integration test")


def _run_alembic(command: list[str]) -> subprocess.CompletedProcess:
    """Run an alembic command via subprocess with the sync DATABASE_URL.

    Uses the venv Python so alembic + psycopg are guaranteed available.
    Raises subprocess.CalledProcessError on non-zero exit.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = _SYNC_DB_URL
    # Locate alembic inside the project venv (consistent with CLAUDE.md commands)
    alembic_bin = os.path.join(
        os.path.dirname(sys.executable), "alembic"
    )
    if not os.path.exists(alembic_bin):
        alembic_bin = "alembic"  # fall back to PATH

    # Repo root = three levels up from tests/integration/<this file> so that
    # alembic.ini is found. (Four dirname() calls overshot to the repo's PARENT,
    # where alembic.ini is absent — alembic then exits 255 with
    # "No 'script_location' key found in configuration".)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    result = subprocess.run(
        [alembic_bin] + command,
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
    )
    if result.returncode != 0:
        # Surface alembic's stderr in the failure message — a silent 255 (empty
        # captured stderr) previously hid a cwd bug for a whole release cycle.
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=f"{result.stderr}\n{result.stdout}",
        )
    return result


async def _column_exists(engine) -> bool:
    """Return True if final_warning_sent_at column exists on appointments table."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :col"
            ),
            {"table": TARGET_TABLE, "col": TARGET_COLUMN},
        )
        return result.fetchone() is not None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_engine():
    """Async engine for column-existence checks."""
    engine = create_async_engine(_ASYNC_DB_URL, echo=False)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Test: upgrade → column exists
# ---------------------------------------------------------------------------


async def test_column_exists_after_upgrade(db_engine) -> None:
    """After alembic upgrade to f1a2b3c4d5e6, final_warning_sent_at column exists (S3-R3).

    RED: fails before T6 creates the migration file (revision not found by alembic).
    GREEN: passes after T6 adds the migration.
    """
    _skip_if_no_postgres()

    # Apply the target migration
    _run_alembic(["upgrade", TARGET_REVISION])

    # Verify column exists
    assert await _column_exists(db_engine), (
        f"Column {TARGET_COLUMN} not found on {TARGET_TABLE} after upgrade to {TARGET_REVISION}. "
        "Either the migration was not applied or the upgrade() function is missing add_column()."
    )


# ---------------------------------------------------------------------------
# Test: downgrade → column absent
# ---------------------------------------------------------------------------


async def test_column_absent_after_downgrade(db_engine) -> None:
    """After alembic downgrade -1 from f1a2b3c4d5e6, final_warning_sent_at is absent (CC-R4).

    Requires test_column_exists_after_upgrade to have run first (upgrade applied).
    """
    _skip_if_no_postgres()

    # Ensure we are at the target revision before downgrading
    _run_alembic(["upgrade", TARGET_REVISION])

    # Downgrade one step (back to parent e1f2a3b4c5d6)
    _run_alembic(["downgrade", "-1"])

    # Verify column is gone
    assert not await _column_exists(db_engine), (
        f"Column {TARGET_COLUMN} still present on {TARGET_TABLE} after downgrade. "
        "downgrade() in the migration may be missing op.drop_column()."
    )


# ---------------------------------------------------------------------------
# Test: re-upgrade → column re-appears (idempotency)
# ---------------------------------------------------------------------------


async def test_column_reappears_after_second_upgrade(db_engine) -> None:
    """After a second upgrade to f1a2b3c4d5e6, column re-appears without error (CC-R4).

    Verifies the migration is idempotent: upgrade → downgrade → upgrade produces
    the same final state without errors.
    """
    _skip_if_no_postgres()

    # Ensure we start at the parent revision
    _run_alembic(["upgrade", TARGET_REVISION])
    _run_alembic(["downgrade", "-1"])

    # Re-upgrade — must not raise
    _run_alembic(["upgrade", TARGET_REVISION])

    assert await _column_exists(db_engine), (
        f"Column {TARGET_COLUMN} did not re-appear after second upgrade to {TARGET_REVISION}. "
        "The migration may not be fully idempotent."
    )

    # Restore to target revision as final state (leave DB at expected head)
    # No teardown downgrade — the migration is the new head in production.
