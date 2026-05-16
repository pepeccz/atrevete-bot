"""Add reminder retry fields to appointments.

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-03-27

Adds retry infrastructure for failed WhatsApp reminder templates:
- reminder_failed: BOOLEAN DEFAULT false — set when a reminder send fails
- reminder_retry_count: INTEGER DEFAULT 0 — tracks number of retry attempts
- reminder_next_retry_at: TIMESTAMPTZ NULL — controls backoff window (15min → 1h)
- idx_appointments_reminder_retry_eligible: partial index (reminder_failed = true) for retry worker
- REMINDER_FAILED enum value: tracks individual failed reminder notifications
- REMINDER_PERMANENTLY_FAILED enum value: escalation after REMINDER_MAX_RETRIES exhausted
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n5o6p7q8r9s0"
down_revision: str | None = "m4n5o6p7q8r9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new enum values for reminder failures
    # (PostgreSQL supports IF NOT EXISTS for safety)
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'reminder_failed'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'reminder_permanently_failed'")

    # Add reminder retry tracking columns to appointments
    op.add_column(
        "appointments",
        sa.Column(
            "reminder_failed",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "reminder_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "reminder_next_retry_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    # Partial index for reminder retry worker — only scans reminder_failed=true rows
    op.create_index(
        "idx_appointments_reminder_retry_eligible",
        "appointments",
        ["reminder_failed", "reminder_retry_count", "reminder_next_retry_at"],
        postgresql_where=sa.text("reminder_failed = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_appointments_reminder_retry_eligible", table_name="appointments")
    op.drop_column("appointments", "reminder_next_retry_at")
    op.drop_column("appointments", "reminder_retry_count")
    op.drop_column("appointments", "reminder_failed")
    # NOTE: PostgreSQL does not support DROP VALUE on enum types.
    # The 'reminder_failed' and 'reminder_permanently_failed' values
    # will remain in the notification_type enum after downgrade.
    # This is a known PostgreSQL limitation — document and accept.
