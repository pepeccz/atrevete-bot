"""add system_settings and system_settings_history tables

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2025-12-12

Adds tables for dynamic configuration management:
- system_settings: Key-value configuration with typed validation
- system_settings_history: Audit trail for all setting changes
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create system_settings table
    op.create_table(
        'system_settings',
        sa.Column('id', sa.UUID(), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('value_type', sa.String(20), nullable=False),
        sa.Column('default_value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('min_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('max_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('allowed_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('label', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('requires_restart', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_by', sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_system_settings_key'),
    )

    # Indexes for system_settings
    op.create_index('idx_system_settings_category', 'system_settings', ['category'])

    # Create system_settings_history table
    op.create_table(
        'system_settings_history',
        sa.Column('id', sa.UUID(), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('setting_id', sa.UUID(), nullable=False),
        sa.Column('setting_key', sa.String(100), nullable=False),
        sa.Column('previous_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('changed_by', sa.String(100), nullable=False),
        sa.Column('change_reason', sa.Text(), nullable=True),
        sa.Column('changed_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['setting_id'], ['system_settings.id'],
                                ondelete='CASCADE'),
    )

    # Indexes for system_settings_history
    op.create_index('idx_settings_history_setting_id', 'system_settings_history',
                    ['setting_id'])
    op.create_index('idx_settings_history_changed_at', 'system_settings_history',
                    [sa.text('changed_at DESC')])
    op.create_index('idx_settings_history_key', 'system_settings_history',
                    ['setting_key'])


def downgrade() -> None:
    # Drop system_settings_history indexes and table
    op.drop_index('idx_settings_history_key', table_name='system_settings_history')
    op.drop_index('idx_settings_history_changed_at', table_name='system_settings_history')
    op.drop_index('idx_settings_history_setting_id', table_name='system_settings_history')
    op.drop_table('system_settings_history')

    # Drop system_settings indexes and table
    op.drop_index('idx_system_settings_category', table_name='system_settings')
    op.drop_table('system_settings')
