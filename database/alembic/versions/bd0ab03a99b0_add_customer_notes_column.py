"""add_customer_notes_column

Revision ID: bd0ab03a99b0
Revises: e8f9a1b2c3d4
Create Date: 2025-11-13 14:52:52.851612

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bd0ab03a99b0'
down_revision: str | None = 'e8f9a1b2c3d4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add notes column to customers table
    op.add_column('customers', sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove notes column from customers table
    op.drop_column('customers', 'notes')
