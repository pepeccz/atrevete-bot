"""add recurring_blocking_series table and recurrence fields to blocking_events

Revision ID: j0k1l2m3n4o5
Revises: h8i9j0k1l2m3
Create Date: 2025-12-14

Adds support for recurring blocking events:
- New table: recurring_blocking_series (stores recurrence patterns)
- New columns in blocking_events: recurring_series_id, occurrence_index, is_exception
- New enum: recurrence_frequency (WEEKLY, MONTHLY)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create recurrence_frequency enum
    recurrence_frequency = postgresql.ENUM(
        'WEEKLY', 'MONTHLY',
        name='recurrence_frequency',
        create_type=False
    )
    recurrence_frequency.create(op.get_bind(), checkfirst=True)

    # Create recurring_blocking_series table
    op.create_table(
        'recurring_blocking_series',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('stylist_id', sa.UUID(), nullable=False),

        # Template fields
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('event_type', postgresql.ENUM(
            'vacation', 'meeting', 'break', 'general', 'personal',
            name='blocking_event_type',
            create_type=False
        ), nullable=False, server_default='general'),

        # Time template (hour:minute of day)
        sa.Column('start_time_of_day', sa.TIME(), nullable=False),
        sa.Column('end_time_of_day', sa.TIME(), nullable=False),

        # RFC 5545 RRULE components (simplified)
        sa.Column('rrule_frequency', postgresql.ENUM(
            'WEEKLY', 'MONTHLY',
            name='recurrence_frequency',
            create_type=False
        ), nullable=False, server_default='WEEKLY'),
        sa.Column('rrule_interval', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('rrule_byday', sa.String(50), nullable=True),  # 'MO,WE,FR'
        sa.Column('rrule_bymonthday', sa.String(50), nullable=True),  # '15,30'
        sa.Column('rrule_count', sa.Integer(), nullable=False),

        # Metadata
        sa.Column('original_start_date', sa.DATE(), nullable=False),
        sa.Column('instances_created', sa.Integer(), nullable=False, server_default='0'),

        # Timestamps
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),

        # Constraints
        sa.CheckConstraint('end_time_of_day > start_time_of_day', name='check_series_end_after_start'),
        sa.CheckConstraint('rrule_count > 0 AND rrule_count <= 52', name='check_series_count_range'),
        sa.CheckConstraint('rrule_interval > 0 AND rrule_interval <= 12', name='check_series_interval_range'),

        # Primary key and foreign keys
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['stylist_id'], ['stylists.id'], ondelete='CASCADE'),
    )

    # Create index for recurring_blocking_series
    op.create_index('idx_recurring_series_stylist', 'recurring_blocking_series', ['stylist_id'])

    # Create trigger for auto-updating updated_at
    op.execute("""
        CREATE TRIGGER update_recurring_blocking_series_updated_at
        BEFORE UPDATE ON recurring_blocking_series
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)

    # Add recurrence fields to blocking_events table
    op.add_column('blocking_events', sa.Column(
        'recurring_series_id',
        sa.UUID(),
        sa.ForeignKey('recurring_blocking_series.id', ondelete='SET NULL'),
        nullable=True
    ))
    op.add_column('blocking_events', sa.Column(
        'occurrence_index',
        sa.Integer(),
        nullable=True
    ))
    op.add_column('blocking_events', sa.Column(
        'is_exception',
        sa.Boolean(),
        nullable=False,
        server_default='false'
    ))

    # Create index for querying instances by series
    op.create_index('idx_blocking_events_series', 'blocking_events', ['recurring_series_id'])


def downgrade() -> None:
    # Drop index for series
    op.drop_index('idx_blocking_events_series', table_name='blocking_events')

    # Remove columns from blocking_events
    op.drop_column('blocking_events', 'is_exception')
    op.drop_column('blocking_events', 'occurrence_index')
    op.drop_column('blocking_events', 'recurring_series_id')

    # Drop trigger
    op.execute('DROP TRIGGER IF EXISTS update_recurring_blocking_series_updated_at ON recurring_blocking_series')

    # Drop index
    op.drop_index('idx_recurring_series_stylist', table_name='recurring_blocking_series')

    # Drop table
    op.drop_table('recurring_blocking_series')

    # Drop enum type
    op.execute('DROP TYPE IF EXISTS recurrence_frequency')
