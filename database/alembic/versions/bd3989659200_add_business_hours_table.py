"""add business hours table

Revision ID: bd3989659200
Revises: 1f737760963f
Create Date: 2025-10-30 18:50:17.960526

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd3989659200'
down_revision: Union[str, None] = '1f737760963f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create business_hours table
    op.create_table(
        'business_hours',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('day_of_week', sa.Integer(), nullable=False),
        sa.Column('is_closed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('start_hour', sa.Integer(), nullable=True),
        sa.Column('start_minute', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('end_hour', sa.Integer(), nullable=True),
        sa.Column('end_minute', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),

        # Constraints
        sa.CheckConstraint('day_of_week >= 0 AND day_of_week <= 6', name='valid_day_of_week'),
        sa.CheckConstraint('start_hour IS NULL OR (start_hour >= 0 AND start_hour <= 23)', name='valid_start_hour'),
        sa.CheckConstraint('start_minute >= 0 AND start_minute <= 59', name='valid_start_minute'),
        sa.CheckConstraint('end_hour IS NULL OR (end_hour >= 0 AND end_hour <= 23)', name='valid_end_hour'),
        sa.CheckConstraint('end_minute >= 0 AND end_minute <= 59', name='valid_end_minute'),

        # Primary key and unique constraint
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('day_of_week', name='unique_day_of_week')
    )

    # Create index on day_of_week
    op.create_index('idx_business_hours_day', 'business_hours', ['day_of_week'])

    # Create trigger for auto-updating updated_at
    op.execute("""
        CREATE TRIGGER update_business_hours_updated_at
        BEFORE UPDATE ON business_hours
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    # Drop trigger
    op.execute('DROP TRIGGER IF EXISTS update_business_hours_updated_at ON business_hours')

    # Drop index
    op.drop_index('idx_business_hours_day', table_name='business_hours')

    # Drop table
    op.drop_table('business_hours')
