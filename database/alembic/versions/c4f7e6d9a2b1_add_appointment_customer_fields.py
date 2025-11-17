"""add_appointment_customer_fields

Add first_name, last_name, and notes fields to appointments table
for storing customer-specific data per appointment.

Revision ID: c4f7e6d9a2b1
Revises: bd0ab03a99b0
Create Date: 2025-11-13 17:07:31.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f7e6d9a2b1'
down_revision: Union[str, None] = 'bd0ab03a99b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add customer-specific fields to appointments table.

    These fields store the customer's name and notes for each individual appointment,
    separate from the customer profile in the customers table.
    """
    # Add first_name column (required)
    op.add_column('appointments', sa.Column('first_name', sa.String(length=100), nullable=False, server_default='Cliente'))

    # Add last_name column (optional)
    op.add_column('appointments', sa.Column('last_name', sa.String(length=100), nullable=True))

    # Add notes column (optional) - for appointment-specific notes (allergies, preferences, etc.)
    op.add_column('appointments', sa.Column('notes', sa.Text(), nullable=True))

    # Remove server_default after adding the column (it was only needed for existing rows)
    op.alter_column('appointments', 'first_name', server_default=None)


def downgrade() -> None:
    """Remove customer-specific fields from appointments table."""
    op.drop_column('appointments', 'notes')
    op.drop_column('appointments', 'last_name')
    op.drop_column('appointments', 'first_name')
