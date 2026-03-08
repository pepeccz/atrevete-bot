"""Add confirmation retry support to appointments.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-03-08

Adds retry infrastructure for failed WhatsApp confirmation templates:
- CONFIRMATION_RETRY enum value: tracks individual retry attempt notifications
- CONFIRMATION_PERMANENTLY_FAILED enum value: escalation after MAX_RETRIES exhausted
- retry_count: INTEGER DEFAULT 0, incremented before each API call (anti-duplicate guard)
- next_retry_at: TIMESTAMPTZ NULL, controls backoff window (30min → 2h → 6h)
- idx_appointments_retry_eligible: partial index (notification_failed = true) for worker queries
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm3n4o5p6q7r8'
down_revision: Union[str, None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values (PostgreSQL supports IF NOT EXISTS for safety)
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'confirmation_retry'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'confirmation_permanently_failed'")

    # Add retry tracking columns to appointments
    op.add_column(
        'appointments',
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'appointments',
        sa.Column('next_retry_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # Partial index for retry worker queries — only scans notification_failed=true rows
    op.create_index(
        'idx_appointments_retry_eligible',
        'appointments',
        ['notification_failed', 'retry_count', 'next_retry_at'],
        postgresql_where=sa.text('notification_failed = true'),
    )


def downgrade() -> None:
    op.drop_index('idx_appointments_retry_eligible', table_name='appointments')
    op.drop_column('appointments', 'next_retry_at')
    op.drop_column('appointments', 'retry_count')
    # NOTE: PostgreSQL does not support DROP VALUE on enum types.
    # The 'confirmation_retry' and 'confirmation_permanently_failed' values
    # will remain in the notification_type enum after downgrade.
    # This is a known PostgreSQL limitation — document and accept.
