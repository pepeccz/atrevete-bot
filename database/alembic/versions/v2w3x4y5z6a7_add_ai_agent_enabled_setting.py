"""add ai_agent_enabled system setting

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-04-10

Adds system-wide AI agent toggle (panic button).
Category: ai_control. Default: true (AI enabled).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v2w3x4y5z6a7"
down_revision: Union[str, None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO system_settings (
            id, category, key, value, value_type, default_value,
            min_value, max_value, allowed_values, label, description,
            requires_restart, display_order, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'ai_control',
            'ai_agent_enabled',
            'true',
            'boolean',
            'true',
            NULL,
            NULL,
            NULL,
            'Agente IA Activo',
            'Activa o desactiva a Maite en todas las conversaciones de WhatsApp. Al desactivar, los mensajes entrantes serán ignorados por la IA y deberán ser atendidos manualmente desde Chatwoot.',
            false,
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM system_settings
        WHERE key = 'ai_agent_enabled'
    """)
