"""add_customer_notes_column

Revision ID: bd0ab03a99b0
Revises: e8f9a1b2c3d4
Create Date: 2025-11-13 14:52:52.851612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd0ab03a99b0'
down_revision: Union[str, None] = 'e8f9a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add notes column to customers table
    op.add_column('customers', sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove notes column from customers table
    op.drop_column('customers', 'notes')
