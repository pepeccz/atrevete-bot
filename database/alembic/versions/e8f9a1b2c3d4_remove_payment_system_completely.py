"""remove_payment_system_completely

Revision ID: e8f9a1b2c3d4
Revises: 3fd622c382cb
Create Date: 2025-11-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e8f9a1b2c3d4'
down_revision: Union[str, None] = '3fd622c382cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Remove entire payment system from database:
    1. Drop payments table completely
    2. Remove payment-related fields from appointments table
    3. Remove payment-related fields from services table
    4. Drop payment_status enum
    """

    # 1. Drop payments table (cascade will handle FK constraints)
    op.drop_table('payments')

    # 2. Remove payment-related fields from appointments table
    # Drop indexes first
    op.drop_index('idx_appointments_stripe_payment_id', table_name='appointments')

    # Drop constraints
    op.drop_constraint('check_appointment_total_price_non_negative', 'appointments', type_='check')
    op.drop_constraint('check_appointment_advance_payment_non_negative', 'appointments', type_='check')
    op.drop_constraint('check_appointment_payment_retry_count_non_negative', 'appointments', type_='check')

    # Drop columns
    op.drop_column('appointments', 'total_price')
    op.drop_column('appointments', 'advance_payment_amount')
    op.drop_column('appointments', 'payment_status')
    op.drop_column('appointments', 'stripe_payment_id')
    op.drop_column('appointments', 'stripe_payment_link_id')
    op.drop_column('appointments', 'payment_retry_count')

    # 3. Remove payment-related fields from services table
    # Drop constraint first
    op.drop_constraint('check_price_non_negative', 'services', type_='check')

    # Drop columns
    op.drop_column('services', 'price_euros')
    op.drop_column('services', 'requires_advance_payment')

    # 4. Drop payment_status enum type
    # First, ensure no other tables are using it (we already dropped the columns above)
    op.execute("DROP TYPE IF EXISTS payment_status CASCADE")


def downgrade() -> None:
    """
    Restore payment system (in case we need to rollback).
    This is the reverse of upgrade().
    """

    # 1. Recreate payment_status enum
    op.execute("""
        CREATE TYPE payment_status AS ENUM ('PENDING', 'CONFIRMED', 'REFUNDED', 'FORFEITED')
    """)

    # 2. Add payment-related fields back to services table
    op.add_column('services', sa.Column('price_euros', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0.00'))
    op.add_column('services', sa.Column('requires_advance_payment', sa.Boolean(), nullable=False, server_default='true'))

    # Add constraint back
    op.create_check_constraint('check_price_non_negative', 'services', 'price_euros >= 0')

    # 3. Add payment-related fields back to appointments table
    op.add_column('appointments', sa.Column('total_price', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0.00'))
    op.add_column('appointments', sa.Column('advance_payment_amount', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0.00'))
    op.add_column('appointments', sa.Column('payment_status',
                                           postgresql.ENUM('PENDING', 'CONFIRMED', 'REFUNDED', 'FORFEITED', name='payment_status', create_type=False),
                                           nullable=False,
                                           server_default='PENDING'))
    op.add_column('appointments', sa.Column('stripe_payment_id', sa.String(length=255), nullable=True))
    op.add_column('appointments', sa.Column('stripe_payment_link_id', sa.String(length=255), nullable=True))
    op.add_column('appointments', sa.Column('payment_retry_count', sa.Integer(), nullable=False, server_default='0'))

    # Add constraints back
    op.create_check_constraint('check_appointment_total_price_non_negative', 'appointments', 'total_price >= 0')
    op.create_check_constraint('check_appointment_advance_payment_non_negative', 'appointments', 'advance_payment_amount >= 0')
    op.create_check_constraint('check_appointment_payment_retry_count_non_negative', 'appointments', 'payment_retry_count >= 0')

    # Add index back
    op.create_index('idx_appointments_stripe_payment_id', 'appointments', ['stripe_payment_id'],
                   unique=False, postgresql_where=sa.text('stripe_payment_id IS NOT NULL'))

    # 4. Recreate payments table
    op.create_table('payments',
        sa.Column('id', sa.UUID(), nullable=False, comment='Unique payment identifier'),
        sa.Column('appointment_id', sa.UUID(), nullable=False, comment='Associated appointment'),
        sa.Column('stripe_payment_intent_id', sa.String(length=255), nullable=False, comment='Stripe PaymentIntent ID (pi_xxx)'),
        sa.Column('stripe_checkout_session_id', sa.String(length=255), nullable=True, comment='Stripe Checkout Session ID (cs_xxx)'),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False, comment='Payment amount in euros'),
        sa.Column('status', postgresql.ENUM('PENDING', 'CONFIRMED', 'REFUNDED', 'FORFEITED', name='payment_status', create_type=False),
                 nullable=False, comment='Payment status'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('stripe_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_payments_appointment_id', 'payments', ['appointment_id'], unique=False)
    op.create_index('idx_payments_status', 'payments', ['status'], unique=False)
    op.create_index(op.f('ix_payments_stripe_payment_intent_id'), 'payments', ['stripe_payment_intent_id'], unique=True)
    op.create_index(op.f('ix_payments_stripe_checkout_session_id'), 'payments', ['stripe_checkout_session_id'], unique=False)
