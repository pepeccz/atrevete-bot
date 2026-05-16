"""add_cancellation_reason_to_appointments

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2025-12-14

Adds cancellation_reason column to appointments table for tracking
why customers cancel their appointments via WhatsApp.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'k1l2m3n4o5p6'
down_revision: str | None = 'j0k1l2m3n4o5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add cancellation_reason column to appointments table
    op.add_column('appointments', sa.Column('cancellation_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove cancellation_reason column from appointments table
    op.drop_column('appointments', 'cancellation_reason')
