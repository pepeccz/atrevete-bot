"""double booking prevention: btree_gist, HOLD status, hold_expires_at, excl_no_overlap

Revision ID: b0c1d2e3f4a5
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
revision = "b0c1d2e3f4a5"
down_revision = "133274b799d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Steps 1 & 2: AUTOCOMMIT-only operations ──────────────────────────────
    # ALTER TYPE ADD VALUE is non-transactional in PostgreSQL — it cannot run
    # inside an open transaction block. We use the raw DBAPI connection directly
    # to set autocommit=True before executing these statements, bypassing
    # SQLAlchemy's transaction management entirely.
    conn = op.get_bind()
    raw_conn = conn.connection  # raw DBAPI connection (psycopg2/psycopg)
    old_autocommit = raw_conn.autocommit
    raw_conn.autocommit = True

    with raw_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        cur.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'hold' BEFORE 'pending'")

    raw_conn.autocommit = old_autocommit

    # ── Step 3: Add hold_expires_at column (transactional DDL) ───────────────
    op.add_column(
        "appointments",
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Step 4: Create IMMUTABLE helper function + GIST exclusion constraint ──
    # PostgreSQL requires all functions in an index expression to be IMMUTABLE.
    # make_interval() is STABLE, not IMMUTABLE, so we wrap the range calculation
    # in a custom IMMUTABLE function that PostgreSQL can safely use in an index.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION appointment_range(start_time timestamptz, duration_minutes int)
            RETURNS tstzrange
            LANGUAGE sql
            IMMUTABLE STRICT PARALLEL SAFE
            AS $$
                SELECT tstzrange(start_time, start_time + (duration_minutes * interval '1 minute'))
            $$
            """
        )
    )

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
                appointment_range(start_time, duration_minutes) WITH &&
            )
            WHERE (status NOT IN ('cancelled', 'no_show', 'completed'))
            """
        )
    )


def downgrade() -> None:
    # Drop GIST exclusion constraint
    op.execute(sa.text("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS excl_no_overlap"))

    # Drop IMMUTABLE helper function
    op.execute(sa.text("DROP FUNCTION IF EXISTS appointment_range(timestamptz, int)"))

    # Drop hold_expires_at column
    op.drop_column("appointments", "hold_expires_at")

    # NOTE: PostgreSQL enum values CANNOT be removed. The 'hold' value added in
    # upgrade() will remain in the appointment_status enum type after downgrade.
    # It becomes unused but does not affect application behaviour.

    # NOTE: btree_gist extension is NOT dropped here. Removing an extension is
    # destructive and may break other constraints relying on it. Run manually if
    # absolutely necessary: DROP EXTENSION btree_gist;
