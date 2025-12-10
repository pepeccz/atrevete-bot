"""add blocking_events and holidays tables for DB-first calendar

Revision ID: a1b2c3d4e5f6
Revises: f8a2c3d4e5f6
Create Date: 2025-12-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f8a2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create blocking_event_type enum
    blocking_event_type = postgresql.ENUM(
        'vacation', 'meeting', 'break', 'general',
        name='blocking_event_type',
        create_type=False
    )
    blocking_event_type.create(op.get_bind(), checkfirst=True)

    # Create blocking_events table
    op.create_table(
        'blocking_events',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('stylist_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('start_time', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('end_time', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('event_type', postgresql.ENUM('vacation', 'meeting', 'break', 'general', name='blocking_event_type', create_type=False), nullable=False, server_default='general'),
        sa.Column('google_calendar_event_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),

        # Constraints
        sa.CheckConstraint('end_time > start_time', name='check_blocking_end_after_start'),

        # Primary key and foreign keys
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['stylist_id'], ['stylists.id'], ondelete='CASCADE'),
    )

    # Create indexes for blocking_events
    op.create_index('idx_blocking_events_stylist_id', 'blocking_events', ['stylist_id'])
    op.create_index(
        'idx_blocking_events_stylist_time',
        'blocking_events',
        ['stylist_id', 'start_time', 'end_time']
    )

    # Create trigger for auto-updating updated_at on blocking_events
    op.execute("""
        CREATE TRIGGER update_blocking_events_updated_at
        BEFORE UPDATE ON blocking_events
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)

    # Create holidays table
    op.create_table(
        'holidays',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('date', sa.DATE(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('is_all_day', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),

        # Primary key and unique constraint
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', name='unique_holiday_date'),
    )

    # Create index for holidays
    op.create_index('idx_holidays_date', 'holidays', ['date'])


def downgrade() -> None:
    # Drop trigger for blocking_events
    op.execute('DROP TRIGGER IF EXISTS update_blocking_events_updated_at ON blocking_events')

    # Drop indexes
    op.drop_index('idx_holidays_date', table_name='holidays')
    op.drop_index('idx_blocking_events_stylist_time', table_name='blocking_events')
    op.drop_index('idx_blocking_events_stylist_id', table_name='blocking_events')

    # Drop tables
    op.drop_table('holidays')
    op.drop_table('blocking_events')

    # Drop enum type
    op.execute('DROP TYPE IF EXISTS blocking_event_type')
