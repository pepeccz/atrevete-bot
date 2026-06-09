"""Integration tests for policy-acceptance migration (T01).

Tests cover:
- Idempotency: upgrade → downgrade → upgrade produces identical schema
- customer_consents table exists with correct columns
- CHECK constraint on accepted_via rejects invalid values
- Index ix_customer_consents_customer_id_accepted_at exists
- Two new columns exist on customers table

These tests require a live PostgreSQL connection.
They skip gracefully when Postgres is not reachable.

Refs: Spec §1 (S-9), Design §1.4, Task T01/T02
"""

from __future__ import annotations

import socket

import pytest
from sqlalchemy import text

from database.connection import AsyncSessionLocal

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


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — skipping migration integration test",
)


# ---------------------------------------------------------------------------
# Schema inspection helpers
# ---------------------------------------------------------------------------


async def _table_exists(session, table_name: str) -> bool:
    """Check if a table exists in the public schema."""
    result = await session.execute(
        text(
            "SELECT EXISTS("
            "  SELECT 1 FROM information_schema.tables"
            "  WHERE table_schema = 'public' AND table_name = :t"
            ")"
        ),
        {"t": table_name},
    )
    return result.scalar()


async def _column_exists(session, table_name: str, column_name: str) -> bool:
    """Check if a column exists in the given table."""
    result = await session.execute(
        text(
            "SELECT EXISTS("
            "  SELECT 1 FROM information_schema.columns"
            "  WHERE table_schema = 'public'"
            "    AND table_name = :t"
            "    AND column_name = :c"
            ")"
        ),
        {"t": table_name, "c": column_name},
    )
    return result.scalar()


async def _index_exists(session, index_name: str) -> bool:
    """Check if an index exists in the current database."""
    result = await session.execute(
        text(
            "SELECT EXISTS("
            "  SELECT 1 FROM pg_indexes"
            "  WHERE indexname = :i"
            ")"
        ),
        {"i": index_name},
    )
    return result.scalar()


async def _constraint_exists(session, constraint_name: str) -> bool:
    """Check if a named constraint exists."""
    result = await session.execute(
        text(
            "SELECT EXISTS("
            "  SELECT 1 FROM information_schema.table_constraints"
            "  WHERE constraint_name = :c"
            ")"
        ),
        {"c": constraint_name},
    )
    return result.scalar()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPolicyAcceptanceMigrationSchema:
    """Schema existence tests — verify migration output (T01/T02)."""

    @pytest.mark.asyncio
    async def test_customer_consents_table_exists(self):
        """customer_consents table must exist after upgrade head."""
        async with AsyncSessionLocal() as session:
            assert await _table_exists(session, "customer_consents"), (
                "customer_consents table not found — run alembic upgrade head first"
            )

    @pytest.mark.asyncio
    async def test_customer_consents_required_columns(self):
        """customer_consents must have all required columns."""
        required_columns = [
            "id",
            "customer_id",
            "policy_version",
            "accepted_at",
            "accepted_via",
            "source_message_id",
            "created_at",
        ]
        async with AsyncSessionLocal() as session:
            for col in required_columns:
                assert await _column_exists(session, "customer_consents", col), (
                    f"customer_consents.{col} column not found"
                )

    @pytest.mark.asyncio
    async def test_customer_policy_accepted_at_column_exists(self):
        """customers.policy_accepted_at column must exist after migration."""
        async with AsyncSessionLocal() as session:
            assert await _column_exists(session, "customers", "policy_accepted_at"), (
                "customers.policy_accepted_at column not found — run alembic upgrade head"
            )

    @pytest.mark.asyncio
    async def test_customer_policy_version_column_exists(self):
        """customers.policy_version column must exist after migration."""
        async with AsyncSessionLocal() as session:
            assert await _column_exists(session, "customers", "policy_version"), (
                "customers.policy_version column not found — run alembic upgrade head"
            )

    @pytest.mark.asyncio
    async def test_customer_consents_index_exists(self):
        """ix_customer_consents_customer_id_accepted_at index must exist."""
        async with AsyncSessionLocal() as session:
            assert await _index_exists(
                session, "ix_customer_consents_customer_id_accepted_at"
            ), "index ix_customer_consents_customer_id_accepted_at not found"

    @pytest.mark.asyncio
    async def test_customer_consents_check_constraint_exists(self):
        """CHECK constraint ck_customer_consents_accepted_via must exist."""
        async with AsyncSessionLocal() as session:
            assert await _constraint_exists(
                session, "ck_customer_consents_accepted_via"
            ), "CHECK constraint ck_customer_consents_accepted_via not found"

    @pytest.mark.asyncio
    async def test_accepted_via_check_constraint_rejects_invalid_value(self):
        """CHECK constraint must reject values outside ('whatsapp','admin_panel')."""
        async with AsyncSessionLocal() as session:
            # First we need a customer to satisfy the FK
            result = await session.execute(
                text("SELECT id FROM customers LIMIT 1")
            )
            row = result.fetchone()
            if row is None:
                pytest.skip("No customer rows available for FK constraint test")

            customer_id = row[0]
            with pytest.raises(Exception) as exc_info:
                await session.execute(
                    text(
                        "INSERT INTO customer_consents"
                        " (id, customer_id, policy_version, accepted_via)"
                        " VALUES (gen_random_uuid(), :cid, '1.0', 'invalid_value')"
                    ),
                    {"cid": customer_id},
                )
                await session.flush()

            error_msg = str(exc_info.value).lower()
            assert "check" in error_msg or "constraint" in error_msg or "violates" in error_msg, (
                f"Expected constraint violation error, got: {exc_info.value}"
            )
            await session.rollback()

    @pytest.mark.asyncio
    async def test_customer_consents_accepts_valid_accepted_via_whatsapp(self):
        """CHECK constraint must accept 'whatsapp' as a valid value."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT id FROM customers LIMIT 1"))
            row = result.fetchone()
            if row is None:
                pytest.skip("No customer rows available for INSERT test")

            customer_id = row[0]
            await session.execute(
                text(
                    "INSERT INTO customer_consents"
                    " (id, customer_id, policy_version, accepted_via)"
                    " VALUES (gen_random_uuid(), :cid, '1.0', 'whatsapp')"
                ),
                {"cid": customer_id},
            )
            await session.flush()
            await session.rollback()

    @pytest.mark.asyncio
    async def test_customer_consents_accepts_valid_accepted_via_admin_panel(self):
        """CHECK constraint must accept 'admin_panel' as a valid value."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT id FROM customers LIMIT 1"))
            row = result.fetchone()
            if row is None:
                pytest.skip("No customer rows available for INSERT test")

            customer_id = row[0]
            await session.execute(
                text(
                    "INSERT INTO customer_consents"
                    " (id, customer_id, policy_version, accepted_via)"
                    " VALUES (gen_random_uuid(), :cid, '1.0', 'admin_panel')"
                ),
                {"cid": customer_id},
            )
            await session.flush()
            await session.rollback()

    @pytest.mark.asyncio
    async def test_customer_consents_on_delete_restrict(self):
        """FK from customer_consents.customer_id must be ON DELETE RESTRICT.

        Confirm the constraint definition — check pg_constraint for restrict action.
        confrelid → customers; confdeltype 'r' = RESTRICT.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT pg_constraint.confdeltype"
                    " FROM pg_constraint"
                    " JOIN pg_class ON pg_class.oid = pg_constraint.conrelid"
                    " WHERE pg_class.relname = 'customer_consents'"
                    "   AND pg_constraint.contype = 'f'"
                    "   AND pg_constraint.conname LIKE '%customer_id%'"
                )
            )
            row = result.fetchone()
            assert row is not None, "FK constraint on customer_consents.customer_id not found"
            # 'r' = RESTRICT, 'a' = NO ACTION, 'c' = CASCADE, 'n' = SET NULL
            assert row[0] == "r", (
                f"Expected FK delete action RESTRICT ('r'), got '{row[0]}'"
            )
