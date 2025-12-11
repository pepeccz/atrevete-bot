"""add notifications table for admin notification center

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2025-12-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create notification_type enum
    notification_type = postgresql.ENUM(
        'appointment_created',
        'appointment_cancelled',
        'appointment_confirmed',
        'appointment_completed',
        name='notification_type',
        create_type=False
    )
    notification_type.create(op.get_bind(), checkfirst=True)

    # Create notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('type', postgresql.ENUM(
            'appointment_created', 'appointment_cancelled',
            'appointment_confirmed', 'appointment_completed',
            name='notification_type', create_type=False
        ), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('read_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # Indexes for efficient querying
    op.create_index('idx_notifications_is_read', 'notifications', ['is_read'])
    op.create_index('idx_notifications_created_at_desc', 'notifications',
                    [sa.text('created_at DESC')])
    op.create_index('idx_notifications_entity', 'notifications',
                    ['entity_type', 'entity_id'])


def downgrade() -> None:
    op.drop_index('idx_notifications_entity', table_name='notifications')
    op.drop_index('idx_notifications_created_at_desc', table_name='notifications')
    op.drop_index('idx_notifications_is_read', table_name='notifications')
    op.drop_table('notifications')
    op.execute('DROP TYPE IF EXISTS notification_type')
