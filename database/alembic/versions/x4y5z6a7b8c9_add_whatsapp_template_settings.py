"""add whatsapp template settings

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-04-26

Inserts 3 WhatsApp HSM template name keys into system_settings:
  - whatsapp_template_confirm_48h
  - whatsapp_template_reminder_24h
  - whatsapp_template_admin_booking

All inserts are idempotent (ON CONFLICT (key) DO NOTHING).
Category: confirmation. Type: string.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "x4y5z6a7b8c9"
down_revision: str | None = "w3x4y5z6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO system_settings (
            id, category, key, value, value_type, default_value,
            min_value, max_value, allowed_values, label, description,
            requires_restart, display_order, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'confirmation',
            'whatsapp_template_confirm_48h',
            'atrevete_confirm_48h',
            'string',
            'atrevete_confirm_48h',
            NULL,
            NULL,
            NULL,
            'Plantilla WhatsApp — Confirmación 48h',
            'Nombre de la plantilla HSM aprobada en Chatwoot para el envío de confirmación 48h antes.',
            false,
            50,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (key) DO NOTHING
    """)

    op.execute("""
        INSERT INTO system_settings (
            id, category, key, value, value_type, default_value,
            min_value, max_value, allowed_values, label, description,
            requires_restart, display_order, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'confirmation',
            'whatsapp_template_reminder_24h',
            'atrevete_reminder_24h',
            'string',
            'atrevete_reminder_24h',
            NULL,
            NULL,
            NULL,
            'Plantilla WhatsApp — Recordatorio 24h',
            'Nombre de la plantilla HSM aprobada en Chatwoot para el recordatorio 24h antes de la cita.',
            false,
            51,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (key) DO NOTHING
    """)

    op.execute("""
        INSERT INTO system_settings (
            id, category, key, value, value_type, default_value,
            min_value, max_value, allowed_values, label, description,
            requires_restart, display_order, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'confirmation',
            'whatsapp_template_admin_booking',
            'appointment_booked_by_admin',
            'string',
            'appointment_booked_by_admin',
            NULL,
            NULL,
            NULL,
            'Plantilla WhatsApp — Reserva por Admin',
            'Nombre de la plantilla HSM aprobada en Chatwoot para notificar al cliente cuando el admin crea una cita.',
            false,
            52,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM system_settings
        WHERE key IN (
            'whatsapp_template_confirm_48h',
            'whatsapp_template_reminder_24h',
            'whatsapp_template_admin_booking'
        )
    """)
