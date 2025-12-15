"""add notification starred fields

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2025-12-15

Adds starred/important functionality to notifications:
- is_starred: Boolean flag to mark notifications as important
- starred_at: Timestamp when notification was starred
- idx_notifications_is_starred: Index for filtering starred notifications
- idx_notifications_type: Index for filtering by notification type
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l2m3n4o5p6q7'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_starred column with default value
    op.add_column(
        'notifications',
        sa.Column('is_starred', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add starred_at timestamp column
    op.add_column(
        'notifications',
        sa.Column('starred_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )

    # Create index for filtering by starred status
    op.create_index(
        'idx_notifications_is_starred',
        'notifications',
        ['is_starred'],
        unique=False
    )

    # Create index for filtering by notification type
    op.create_index(
        'idx_notifications_type',
        'notifications',
        ['type'],
        unique=False
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_notifications_type', table_name='notifications')
    op.drop_index('idx_notifications_is_starred', table_name='notifications')

    # Drop columns
    op.drop_column('notifications', 'starred_at')
    op.drop_column('notifications', 'is_starred')
