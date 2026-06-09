"""add gcal sync status to appointments

Revision ID: e1f2a3b4c5d6
Revises: b9d4e8f1c2a3
Create Date: 2026-06-07 21:00:00.000000

Adds four columns to track Google Calendar sync state per appointment:
  - gcal_sync_status VARCHAR(20) NOT NULL DEFAULT 'synced'
  - gcal_last_attempt_at TIMESTAMPTZ NULL
  - gcal_last_error TEXT NULL
  - gcal_operation VARCHAR(20) NULL

Design: D1 (gcal-sync-resilience). VARCHAR not PG ENUM — cheaper future migrations.
Server default 'synced' keeps the column NOT NULL safe for existing rows
(which already have a google_calendar_event_id, so synced is the correct historical state).
gcal_operation IS NULL for pre-migration rows (AS9).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "b9d4e8f1c2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column(
            "gcal_sync_status",
            sa.String(20),
            nullable=False,
            server_default="synced",
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "gcal_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "gcal_last_error",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "gcal_operation",
            sa.String(20),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("appointments", "gcal_operation")
    op.drop_column("appointments", "gcal_last_error")
    op.drop_column("appointments", "gcal_last_attempt_at")
    op.drop_column("appointments", "gcal_sync_status")
