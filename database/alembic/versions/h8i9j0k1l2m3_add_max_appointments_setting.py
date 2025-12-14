"""add max_pending_appointments_per_customer setting

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2025-12-13

Adds configurable limit for pending appointments per customer from WhatsApp agent.
Default: 3 appointments. Range: 1-10.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Insert the new system setting for max pending appointments
    op.execute("""
        INSERT INTO system_settings (
            id, category, key, value, value_type, default_value,
            min_value, max_value, allowed_values, label, description,
            requires_restart, display_order, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'booking',
            'max_pending_appointments_per_customer',
            '3',
            'int',
            '3',
            '1',
            '10',
            NULL,
            'Citas pendientes máx. por cliente',
            'Número máximo de citas futuras (pendientes o confirmadas) que un cliente puede tener activas. Solo aplica a reservas desde WhatsApp.',
            false,
            15,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM system_settings
        WHERE key = 'max_pending_appointments_per_customer'
    """)
