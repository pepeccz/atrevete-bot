"""Create transactional tables: appointments, policies, conversation_history

Revision ID: de6f4bde8b7
Revises: 1a030dcddf99
Create Date: 2025-10-27 09:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'de6f4bde8b7'
down_revision: str | None = '1a030dcddf99'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Set timezone to Europe/Madrid
    op.execute("SET timezone='Europe/Madrid'")

    # Create policies table
    op.create_table('policies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_policies_key', 'policies', ['key'], unique=True)

    # Create trigger for policies.updated_at
    op.execute("""
        CREATE TRIGGER update_policies_updated_at
        BEFORE UPDATE ON policies
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)

    # Create appointments table
    op.create_table('appointments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('stylist_id', sa.UUID(), nullable=False),
        sa.Column('service_ids', sa.ARRAY(sa.UUID()), nullable=False),
        sa.Column('pack_id', sa.UUID(), nullable=True),
        sa.Column('start_time', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('total_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('advance_payment_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('payment_status', sa.Enum('pending', 'confirmed', 'refunded', 'forfeited', name='payment_status'), nullable=False),
        sa.Column('status', sa.Enum('provisional', 'confirmed', 'completed', 'cancelled', 'expired', name='appointment_status'), nullable=False),
        sa.Column('google_calendar_event_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_payment_id', sa.String(length=255), nullable=True),
        sa.Column('payment_retry_count', sa.Integer(), nullable=False),
        sa.Column('reminder_sent', sa.Boolean(), nullable=False),
        sa.Column('group_booking_id', sa.UUID(), nullable=True),
        sa.Column('booked_by_customer_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint('duration_minutes > 0', name='check_appointment_duration_positive'),
        sa.CheckConstraint('total_price >= 0', name='check_appointment_total_price_non_negative'),
        sa.CheckConstraint('advance_payment_amount >= 0', name='check_appointment_advance_payment_non_negative'),
        sa.CheckConstraint('payment_retry_count >= 0', name='check_appointment_payment_retry_count_non_negative'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['stylist_id'], ['stylists.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['pack_id'], ['packs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['booked_by_customer_id'], ['customers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for appointments table
    op.create_index('idx_appointments_customer_id', 'appointments', ['customer_id'], unique=False)
    op.create_index('idx_appointments_stylist_id', 'appointments', ['stylist_id'], unique=False)
    op.create_index('idx_appointments_start_time', 'appointments', ['start_time'], unique=False)
    op.create_index('idx_appointments_status', 'appointments', ['status'], unique=False)

    # Conditional indexes for appointments
    op.create_index(
        'idx_appointments_stripe_payment_id',
        'appointments',
        ['stripe_payment_id'],
        unique=False,
        postgresql_where=sa.text('stripe_payment_id IS NOT NULL')
    )
    op.create_index(
        'idx_appointments_group_booking_id',
        'appointments',
        ['group_booking_id'],
        unique=False,
        postgresql_where=sa.text('group_booking_id IS NOT NULL')
    )
    op.create_index(
        'idx_appointments_reminder_status',
        'appointments',
        ['start_time', 'reminder_sent', 'status'],
        unique=False
    )

    # Create trigger for appointments.updated_at
    op.execute("""
        CREATE TRIGGER update_appointments_updated_at
        BEFORE UPDATE ON appointments
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)

    # Create conversation_history table
    op.create_table('conversation_history',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.String(length=255), nullable=False),
        sa.Column('timestamp', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('message_role', sa.Enum('user', 'assistant', 'system', name='message_role'), nullable=False),
        sa.Column('message_content', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for conversation_history table
    op.create_index('idx_conversation_history_customer_id', 'conversation_history', ['customer_id'], unique=False)
    op.create_index('idx_conversation_history_conversation_timestamp', 'conversation_history', ['conversation_id', 'timestamp'], unique=False)
    op.create_index(
        'idx_conversation_history_timestamp_desc',
        'conversation_history',
        ['timestamp'],
        unique=False,
        postgresql_ops={'timestamp': 'DESC'}
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('conversation_history')
    op.drop_table('appointments')
    op.drop_table('policies')

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS message_role")
    op.execute("DROP TYPE IF EXISTS appointment_status")
    op.execute("DROP TYPE IF EXISTS payment_status")
