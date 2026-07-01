"""add final_warning_sent_at to appointments

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-07-01

Adds one nullable TIMESTAMPTZ column to appointments for the Slice-3
auto-cancel tail (reactivate-confirmation-lifecycle):

  final_warning_sent_at TIMESTAMPTZ NULL

State-machine role: confirmation_sent → grace → final_warning_sent → grace → CANCELLED.
mark_sent_fn uses a compare-and-set UPDATE WHERE final_warning_sent_at IS NULL for
at-most-once delivery (mirrors confirm_48h's confirmation_sent_at pattern).

No backfill: column defaults NULL. All existing rows are CONFIRMED/CANCELLED/etc. —
they never satisfy status = 'PENDING' in the new handlers, so they are safe (S3-R10,
CC-R4, I-SAFE baseline invariant).

Optional partial index idx_appointments_auto_cancel_eligible covers the query pattern
for both final-warning and auto-cancel handlers:
  WHERE status = 'pending' AND final_warning_sent_at IS NULL (final-warning phase)
  WHERE status = 'pending' AND final_warning_sent_at IS NOT NULL (auto-cancel phase)

Parent: e1f2a3b4c5d6 (add_gcal_sync_status_to_appointments — verified current head).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the final_warning_sent_at column — nullable, no server_default, no backfill.
    # All existing rows receive NULL (safe — they are CONFIRMED/CANCELLED and never
    # matched by the PENDING filter in the new handlers).
    op.add_column(
        "appointments",
        sa.Column(
            "final_warning_sent_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    # Optional partial index for query performance.
    # Covers both handler phases:
    #   final-warning: WHERE status='pending' AND confirmation_sent_at IS NOT NULL
    #                         AND final_warning_sent_at IS NULL
    #   auto-cancel:   WHERE status='pending' AND final_warning_sent_at IS NOT NULL
    # The index is created on (final_warning_sent_at, confirmation_sent_at) WHERE
    # status='pending' to keep the index sparse (only PENDING rows, which are the
    # active working set).
    op.create_index(
        "idx_appointments_auto_cancel_eligible",
        "appointments",
        ["final_warning_sent_at", "confirmation_sent_at"],
        postgresql_where=text("status = 'pending'"),
    )


def downgrade() -> None:
    # Drop in reverse order: index first, then column.
    op.drop_index(
        "idx_appointments_auto_cancel_eligible",
        table_name="appointments",
    )
    op.drop_column("appointments", "final_warning_sent_at")
