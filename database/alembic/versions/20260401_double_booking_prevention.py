"""double booking prevention: btree_gist, HOLD status, hold_expires_at, excl_no_overlap

Revision ID: a1b2c3d4e5f6
Revises: 133274b799d3
Create Date: 2026-04-01

Changes:
1. Install btree_gist extension (required for GIST index on UUID + tstzrange)
2. Add 'hold' value to appointment_status PostgreSQL enum
3. Add hold_expires_at column (TIMESTAMP WITH TIME ZONE, nullable)
4. Add excl_no_overlap GIST exclusion constraint (prevents overlapping active appointments per stylist)

IMPORTANT — AUTOCOMMIT CAVEAT:
  `ALTER TYPE ... ADD VALUE` cannot run inside a transaction in PostgreSQL.
  The upgrade() function uses raw connection AUTOCOMMIT for steps 1 & 2.
  If this migration fails with "ALTER TYPE cannot run inside a transaction block",
  verify that `transaction_per_migration = false` is NOT set in alembic.ini
  AND that you are using Alembic >= 1.13 with the pattern below.

DOWNGRADE NOTE:
  PostgreSQL enum values cannot be dropped once added. After downgrade, the 'hold'
  value remains in the appointment_status enum but is unused by application code.
  btree_gist extension is not dropped (may be shared with other constraints).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "133274b799d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Steps 1 & 2: AUTOCOMMIT-only operations ──────────────────────────────
    # ALTER TYPE ADD VALUE is non-transactional in PostgreSQL — it cannot run
    # inside an open transaction block. We get a raw DBAPI connection and set
    # AUTOCOMMIT before executing these statements, then restore the default
    # isolation level for the remaining transactional DDL.
    conn = op.get_bind()
    conn.execution_options(isolation_level="AUTOCOMMIT")

    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    conn.execute(
        sa.text("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'hold' BEFORE 'pending'")
    )

    # Restore default isolation level for the remaining transactional DDL
    conn.execution_options(isolation_level="DEFAULT")

    # ── Step 3: Add hold_expires_at column (transactional DDL) ───────────────
    op.add_column(
        "appointments",
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Step 4: Add GIST exclusion constraint ────────────────────────────────
    # Prevents two active appointments for the same stylist from overlapping.
    # Partial predicate excludes terminal statuses (cancelled, no_show, completed)
    # and is additive — existing PENDING/CONFIRMED appointments are unaffected
    # unless they actually overlap.
    op.execute(
        sa.text(
            """
            ALTER TABLE appointments
            ADD CONSTRAINT excl_no_overlap
            EXCLUDE USING GIST (
                stylist_id WITH =,
                tstzrange(
                    start_time,
                    start_time + make_interval(mins => duration_minutes)
                ) WITH &&
            )
            WHERE (status NOT IN ('cancelled', 'no_show', 'completed'))
            """
        )
    )


def downgrade() -> None:
    # Drop GIST exclusion constraint
    op.execute(sa.text("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS excl_no_overlap"))

    # Drop hold_expires_at column
    op.drop_column("appointments", "hold_expires_at")

    # NOTE: PostgreSQL enum values CANNOT be removed. The 'hold' value added in
    # upgrade() will remain in the appointment_status enum type after downgrade.
    # It becomes unused but does not affect application behaviour.

    # NOTE: btree_gist extension is NOT dropped here. Removing an extension is
    # destructive and may break other constraints relying on it. Run manually if
    # absolutely necessary: DROP EXTENSION btree_gist;
