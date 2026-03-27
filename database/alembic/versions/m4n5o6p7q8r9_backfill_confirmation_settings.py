"""backfill confirmation worker settings

Revision ID: m4n5o6p7q8r9
Revises: h8i9j0k1l2m3
Create Date: 2026-03-27

Backfill 9 confirmation-worker settings (confirmation_job_time, auto_cancel_job_time,
reminder_job_interval, confirmation_hours_before, auto_cancel_hours_before,
reminder_hours_before, confirmation_template_name, auto_cancel_template_name,
reminder_template_name) for both new and existing deployments.

Uses ON CONFLICT (key) DO NOTHING for idempotent inserts.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'm4n5o6p7q8r9'
down_revision: Union[str, None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Insert the 9 confirmation-worker settings using idempotent ON CONFLICT
    op.execute("""
        INSERT INTO system_settings (
            id, category, key, value, value_type, default_value,
            min_value, max_value, allowed_values, label, description,
            requires_restart, display_order, created_at, updated_at
        ) VALUES
        (gen_random_uuid(), 'confirmation', 'confirmation_job_time', '10:00', 'string', '10:00',
         NULL, NULL, NULL, 'Hora de envío de confirmaciones',
         'Hora del día (HH:MM) en que se envían las solicitudes de confirmación de citas. Formato 24h.',
         true, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        (gen_random_uuid(), 'confirmation', 'auto_cancel_job_time', '10:00', 'string', '10:00',
         NULL, NULL, NULL, 'Hora de cancelaciones automáticas',
         'Hora del día (HH:MM) en que se procesan las cancelaciones automáticas de citas no confirmadas.',
         true, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        (gen_random_uuid(), 'confirmation', 'reminder_job_interval', 'hourly', 'enum', 'hourly',
         NULL, NULL, '["hourly", "30min"]', 'Intervalo de recordatorios',
         'Con qué frecuencia se ejecuta el job de envío de recordatorios.',
         true, 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        (gen_random_uuid(), 'confirmation', 'confirmation_hours_before', '48', 'int', '48',
         '24', '72', NULL, 'Horas antes para confirmar',
         'Cuántas horas antes de la cita se envía la solicitud de confirmación.',
         false, 4, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        (gen_random_uuid(), 'confirmation', 'auto_cancel_hours_before', '24', 'int', '24',
         '12', '48', NULL, 'Horas antes para cancelar',
         'Cuántas horas antes de la cita se cancela automáticamente si no fue confirmada.',
         false, 5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        (gen_random_uuid(), 'confirmation', 'reminder_hours_before', '2', 'int', '2',
         '1', '24', NULL, 'Horas antes para recordatorio',
         'Cuántas horas antes de la cita se envía el recordatorio final.',
         false, 6, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        (gen_random_uuid(), 'confirmation', 'confirmation_template_name', 'appointment_confirmation_48h', 'string', 'appointment_confirmation_48h',
         NULL, NULL, NULL, 'Template de confirmación',
         'Nombre del template de Chatwoot para solicitudes de confirmación.',
         false, 7, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        (gen_random_uuid(), 'confirmation', 'auto_cancel_template_name', 'appointment_auto_cancelled', 'string', 'appointment_auto_cancelled',
         NULL, NULL, NULL, 'Template de cancelación',
         'Nombre del template de Chatwoot para notificaciones de cancelación automática.',
         false, 8, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        (gen_random_uuid(), 'confirmation', 'reminder_template_name', 'appointment_reminder_2h', 'string', 'appointment_reminder_2h',
         NULL, NULL, NULL, 'Template de recordatorio',
         'Nombre del template de Chatwoot para recordatorios de cita.',
         false, 9, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM system_settings
        WHERE key IN (
            'confirmation_job_time',
            'auto_cancel_job_time',
            'reminder_job_interval',
            'confirmation_hours_before',
            'auto_cancel_hours_before',
            'reminder_hours_before',
            'confirmation_template_name',
            'auto_cancel_template_name',
            'reminder_template_name'
        )
    """)
