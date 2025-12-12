"""add gcal_sync_state table for incremental sync

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2025-12-12

Adds table for tracking Google Calendar sync state per stylist:
- gcal_sync_state: Stores sync tokens for incremental sync
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create gcal_sync_state table
    op.create_table(
        'gcal_sync_state',
        sa.Column('id', sa.UUID(), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('stylist_id', sa.UUID(), nullable=False),
        sa.Column('sync_token', sa.String(500), nullable=True),
        sa.Column('last_sync_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('events_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['stylist_id'], ['stylists.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('stylist_id', name='uq_gcal_sync_state_stylist'),
    )

    # Index for efficient lookups
    op.create_index('idx_gcal_sync_state_stylist_id', 'gcal_sync_state', ['stylist_id'])


def downgrade() -> None:
    op.drop_index('idx_gcal_sync_state_stylist_id', table_name='gcal_sync_state')
    op.drop_table('gcal_sync_state')
