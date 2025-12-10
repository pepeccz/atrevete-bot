"""add personal value to blocking_event_type enum

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-12-10 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'personal' value to blocking_event_type enum
    # PostgreSQL requires ALTER TYPE to add new enum values
    op.execute("ALTER TYPE blocking_event_type ADD VALUE IF NOT EXISTS 'personal'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values directly
    # This would require recreating the type and all dependent columns
    # For safety, we leave this as a no-op
    pass
