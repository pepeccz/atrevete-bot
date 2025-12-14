"""
Seed data for system_settings table.

Contains 30+ configurable parameters organized in 7 categories:
- confirmation: Appointment confirmation and reminder settings
- booking: Booking rules and constraints
- llm: LLM model and temperature settings
- rate_limiting: API rate limits and login protection
- cache: Cache TTL and performance settings
- archival: Conversation archival settings
- gcal_sync: Google Calendar sync settings

Usage:
    DATABASE_URL="postgresql+asyncpg://..." python -m database.seeds.system_settings_seed
"""
import asyncio
import sys
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, str(__file__).rsplit("/database", 1)[0])
sys.path.insert(0, str(__file__).rsplit("\\database", 1)[0])

from database.models import SystemSetting, SettingValueType, SettingCategory
from shared.config import get_settings


# All system settings organized by category
SYSTEM_SETTINGS = [
    # ========== CONFIRMATION SETTINGS (9) ==========
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "confirmation_job_time",
        "value": "10:00",
        "value_type": SettingValueType.STRING.value,
        "default_value": "10:00",
        "min_value": None,
        "max_value": None,
        "allowed_values": None,
        "label": "Hora de envío de confirmaciones",
        "description": "Hora del día (HH:MM) en que se envían las solicitudes de confirmación de citas. Formato 24h.",
        "requires_restart": True,
        "display_order": 1,
    },
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "auto_cancel_job_time",
        "value": "10:00",
        "value_type": SettingValueType.STRING.value,
        "default_value": "10:00",
        "min_value": None,
        "max_value": None,
        "allowed_values": None,
        "label": "Hora de cancelaciones automáticas",
        "description": "Hora del día (HH:MM) en que se procesan las cancelaciones automáticas de citas no confirmadas.",
        "requires_restart": True,
        "display_order": 2,
    },
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "reminder_job_interval",
        "value": "hourly",
        "value_type": SettingValueType.ENUM.value,
        "default_value": "hourly",
        "min_value": None,
        "max_value": None,
        "allowed_values": ["hourly", "30min"],
        "label": "Intervalo de recordatorios",
        "description": "Con qué frecuencia se ejecuta el job de envío de recordatorios.",
        "requires_restart": True,
        "display_order": 3,
    },
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "confirmation_hours_before",
        "value": 48,
        "value_type": SettingValueType.INT.value,
        "default_value": 48,
        "min_value": 24,
        "max_value": 72,
        "allowed_values": None,
        "label": "Horas antes para confirmar",
        "description": "Cuántas horas antes de la cita se envía la solicitud de confirmación.",
        "requires_restart": False,
        "display_order": 4,
    },
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "auto_cancel_hours_before",
        "value": 24,
        "value_type": SettingValueType.INT.value,
        "default_value": 24,
        "min_value": 12,
        "max_value": 48,
        "allowed_values": None,
        "label": "Horas antes para cancelar",
        "description": "Cuántas horas antes de la cita se cancela automáticamente si no fue confirmada.",
        "requires_restart": False,
        "display_order": 5,
    },
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "reminder_hours_before",
        "value": 2,
        "value_type": SettingValueType.INT.value,
        "default_value": 2,
        "min_value": 1,
        "max_value": 24,
        "allowed_values": None,
        "label": "Horas antes para recordatorio",
        "description": "Cuántas horas antes de la cita se envía el recordatorio final.",
        "requires_restart": False,
        "display_order": 6,
    },
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "confirmation_template_name",
        "value": "appointment_confirmation_48h",
        "value_type": SettingValueType.STRING.value,
        "default_value": "appointment_confirmation_48h",
        "min_value": None,
        "max_value": None,
        "allowed_values": None,
        "label": "Template de confirmación",
        "description": "Nombre del template de Chatwoot para solicitudes de confirmación.",
        "requires_restart": False,
        "display_order": 7,
    },
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "auto_cancel_template_name",
        "value": "appointment_auto_cancelled",
        "value_type": SettingValueType.STRING.value,
        "default_value": "appointment_auto_cancelled",
        "min_value": None,
        "max_value": None,
        "allowed_values": None,
        "label": "Template de cancelación",
        "description": "Nombre del template de Chatwoot para notificaciones de cancelación automática.",
        "requires_restart": False,
        "display_order": 8,
    },
    {
        "category": SettingCategory.CONFIRMATION.value,
        "key": "reminder_template_name",
        "value": "appointment_reminder_2h",
        "value_type": SettingValueType.STRING.value,
        "default_value": "appointment_reminder_2h",
        "min_value": None,
        "max_value": None,
        "allowed_values": None,
        "label": "Template de recordatorio",
        "description": "Nombre del template de Chatwoot para recordatorios de cita.",
        "requires_restart": False,
        "display_order": 9,
    },

    # ========== BOOKING SETTINGS (6) ==========
    {
        "category": SettingCategory.BOOKING.value,
        "key": "minimum_booking_days_advance",
        "value": 3,
        "value_type": SettingValueType.INT.value,
        "default_value": 3,
        "min_value": 0,
        "max_value": 14,
        "allowed_values": None,
        "label": "Días mínimos de antelación",
        "description": "Número mínimo de días de antelación requeridos para hacer una reserva.",
        "requires_restart": False,
        "display_order": 10,
    },
    {
        "category": SettingCategory.BOOKING.value,
        "key": "same_day_buffer_hours",
        "value": 1,
        "value_type": SettingValueType.INT.value,
        "default_value": 1,
        "min_value": 0,
        "max_value": 6,
        "allowed_values": None,
        "label": "Buffer para mismo día (horas)",
        "description": "Horas mínimas de antelación para reservas del mismo día.",
        "requires_restart": False,
        "display_order": 11,
    },
    {
        "category": SettingCategory.BOOKING.value,
        "key": "max_slots_to_present",
        "value": 3,
        "value_type": SettingValueType.INT.value,
        "default_value": 3,
        "min_value": 1,
        "max_value": 10,
        "allowed_values": None,
        "label": "Máximo de slots a mostrar",
        "description": "Número máximo de slots de disponibilidad a presentar al cliente.",
        "requires_restart": False,
        "display_order": 12,
    },
    {
        "category": SettingCategory.BOOKING.value,
        "key": "buffer_minutes_between_appointments",
        "value": 0,
        "value_type": SettingValueType.INT.value,
        "default_value": 0,
        "min_value": 0,
        "max_value": 30,
        "allowed_values": None,
        "label": "Buffer entre citas (minutos)",
        "description": "Minutos de buffer entre citas consecutivas.",
        "requires_restart": False,
        "display_order": 13,
    },
    {
        "category": SettingCategory.BOOKING.value,
        "key": "default_service_duration_minutes",
        "value": 90,
        "value_type": SettingValueType.INT.value,
        "default_value": 90,
        "min_value": 30,
        "max_value": 180,
        "allowed_values": None,
        "label": "Duración por defecto (minutos)",
        "description": "Duración por defecto de un servicio si no está especificada.",
        "requires_restart": False,
        "display_order": 14,
    },
    {
        "category": SettingCategory.BOOKING.value,
        "key": "max_pending_appointments_per_customer",
        "value": 3,
        "value_type": SettingValueType.INT.value,
        "default_value": 3,
        "min_value": 1,
        "max_value": 10,
        "allowed_values": None,
        "label": "Citas pendientes máx. por cliente",
        "description": "Número máximo de citas futuras (pendientes o confirmadas) que un cliente puede tener activas. Solo aplica a reservas desde WhatsApp.",
        "requires_restart": False,
        "display_order": 15,
    },

    # ========== LLM SETTINGS (6) ==========
    {
        "category": SettingCategory.LLM.value,
        "key": "llm_model",
        "value": "openai/gpt-4o-mini",
        "value_type": SettingValueType.STRING.value,
        "default_value": "openai/gpt-4o-mini",
        "min_value": None,
        "max_value": None,
        "allowed_values": None,
        "label": "Modelo LLM",
        "description": "Modelo de lenguaje a utilizar (formato OpenRouter: provider/model).",
        "requires_restart": False,
        "display_order": 15,
    },
    {
        "category": SettingCategory.LLM.value,
        "key": "intent_extraction_temperature",
        "value": 0.1,
        "value_type": SettingValueType.FLOAT.value,
        "default_value": 0.1,
        "min_value": 0.0,
        "max_value": 1.0,
        "allowed_values": None,
        "label": "Temperatura extracción de intención",
        "description": "Temperatura del LLM para extracción de intención (menor = más determinista).",
        "requires_restart": False,
        "display_order": 16,
    },
    {
        "category": SettingCategory.LLM.value,
        "key": "conversational_temperature",
        "value": 0.3,
        "value_type": SettingValueType.FLOAT.value,
        "default_value": 0.3,
        "min_value": 0.0,
        "max_value": 1.0,
        "allowed_values": None,
        "label": "Temperatura conversacional",
        "description": "Temperatura del LLM para respuestas conversacionales.",
        "requires_restart": False,
        "display_order": 17,
    },
    {
        "category": SettingCategory.LLM.value,
        "key": "summarization_temperature",
        "value": 0.3,
        "value_type": SettingValueType.FLOAT.value,
        "default_value": 0.3,
        "min_value": 0.0,
        "max_value": 1.0,
        "allowed_values": None,
        "label": "Temperatura resumen",
        "description": "Temperatura del LLM para generación de resúmenes.",
        "requires_restart": False,
        "display_order": 18,
    },
    {
        "category": SettingCategory.LLM.value,
        "key": "llm_request_timeout_seconds",
        "value": 30,
        "value_type": SettingValueType.INT.value,
        "default_value": 30,
        "min_value": 5,
        "max_value": 120,
        "allowed_values": None,
        "label": "Timeout de requests (segundos)",
        "description": "Tiempo máximo de espera para respuestas del LLM.",
        "requires_restart": False,
        "display_order": 19,
    },
    {
        "category": SettingCategory.LLM.value,
        "key": "llm_max_retries",
        "value": 2,
        "value_type": SettingValueType.INT.value,
        "default_value": 2,
        "min_value": 0,
        "max_value": 5,
        "allowed_values": None,
        "label": "Reintentos máximos",
        "description": "Número máximo de reintentos ante fallos del LLM.",
        "requires_restart": False,
        "display_order": 20,
    },

    # ========== RATE LIMITING SETTINGS (3) ==========
    {
        "category": SettingCategory.RATE_LIMITING.value,
        "key": "rate_limit_requests_per_minute",
        "value": 10,
        "value_type": SettingValueType.INT.value,
        "default_value": 10,
        "min_value": 5,
        "max_value": 100,
        "allowed_values": None,
        "label": "Requests por minuto",
        "description": "Límite de requests por minuto por usuario/IP.",
        "requires_restart": False,
        "display_order": 21,
    },
    {
        "category": SettingCategory.RATE_LIMITING.value,
        "key": "login_max_attempts",
        "value": 5,
        "value_type": SettingValueType.INT.value,
        "default_value": 5,
        "min_value": 3,
        "max_value": 20,
        "allowed_values": None,
        "label": "Intentos máximos de login",
        "description": "Número máximo de intentos de login antes de bloquear.",
        "requires_restart": False,
        "display_order": 22,
    },
    {
        "category": SettingCategory.RATE_LIMITING.value,
        "key": "login_lockout_minutes",
        "value": 5,
        "value_type": SettingValueType.INT.value,
        "default_value": 5,
        "min_value": 1,
        "max_value": 60,
        "allowed_values": None,
        "label": "Tiempo de bloqueo (minutos)",
        "description": "Duración del bloqueo tras exceder intentos de login.",
        "requires_restart": False,
        "display_order": 23,
    },

    # ========== CACHE SETTINGS (3) ==========
    {
        "category": SettingCategory.CACHE.value,
        "key": "stylist_cache_ttl_seconds",
        "value": 600,
        "value_type": SettingValueType.INT.value,
        "default_value": 600,
        "min_value": 60,
        "max_value": 3600,
        "allowed_values": None,
        "label": "Cache de estilistas (segundos)",
        "description": "TTL del cache de información de estilistas.",
        "requires_restart": False,
        "display_order": 24,
    },
    {
        "category": SettingCategory.CACHE.value,
        "key": "message_batch_window_seconds",
        "value": 30,
        "value_type": SettingValueType.INT.value,
        "default_value": 30,
        "min_value": 0,
        "max_value": 120,
        "allowed_values": None,
        "label": "Ventana de batch mensajes (segundos)",
        "description": "Tiempo para agrupar mensajes consecutivos del mismo usuario.",
        "requires_restart": False,
        "display_order": 25,
    },
    {
        "category": SettingCategory.CACHE.value,
        "key": "max_messages_in_state",
        "value": 10,
        "value_type": SettingValueType.INT.value,
        "default_value": 10,
        "min_value": 5,
        "max_value": 20,
        "allowed_values": None,
        "label": "Máximo mensajes en estado",
        "description": "Número máximo de mensajes a mantener en el estado antes de resumir.",
        "requires_restart": False,
        "display_order": 26,
    },

    # ========== ARCHIVAL SETTINGS (2) ==========
    {
        "category": SettingCategory.ARCHIVAL.value,
        "key": "archival_cutoff_hours",
        "value": 23,
        "value_type": SettingValueType.INT.value,
        "default_value": 23,
        "min_value": 12,
        "max_value": 24,
        "allowed_values": None,
        "label": "Horas para archivar",
        "description": "Horas de inactividad tras las cuales se archiva una conversación.",
        "requires_restart": False,
        "display_order": 27,
    },
    {
        "category": SettingCategory.ARCHIVAL.value,
        "key": "archival_max_retry_attempts",
        "value": 2,
        "value_type": SettingValueType.INT.value,
        "default_value": 2,
        "min_value": 1,
        "max_value": 5,
        "allowed_values": None,
        "label": "Reintentos de archivado",
        "description": "Número máximo de reintentos para archivar una conversación.",
        "requires_restart": False,
        "display_order": 28,
    },

    # ========== GCAL SYNC SETTINGS (2) ==========
    {
        "category": SettingCategory.GCAL_SYNC.value,
        "key": "gcal_sync_interval_minutes",
        "value": 5,
        "value_type": SettingValueType.INT.value,
        "default_value": 5,
        "min_value": 1,
        "max_value": 60,
        "allowed_values": None,
        "label": "Intervalo de sincronización (minutos)",
        "description": "Cada cuántos minutos se sincroniza con Google Calendar. Menor = más actualizado pero más uso de API.",
        "requires_restart": True,
        "display_order": 29,
    },
    {
        "category": SettingCategory.GCAL_SYNC.value,
        "key": "gcal_sync_enabled",
        "value": True,
        "value_type": SettingValueType.BOOLEAN.value,
        "default_value": True,
        "min_value": None,
        "max_value": None,
        "allowed_values": None,
        "label": "Sincronización habilitada",
        "description": "Habilitar/deshabilitar la sincronización bidireccional con Google Calendar.",
        "requires_restart": False,
        "display_order": 30,
    },
]


async def seed_system_settings(db_url: str | None = None) -> None:
    """Seed system_settings table with default configuration values."""
    if db_url is None:
        settings = get_settings()
        db_url = settings.DATABASE_URL

    # Ensure we use asyncpg driver
    if "postgresql://" in db_url and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    if "postgresql+psycopg://" in db_url:
        db_url = db_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")

    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        inserted = 0
        updated = 0

        for setting_data in SYSTEM_SETTINGS:
            # Check if setting already exists
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == setting_data["key"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update only metadata fields, preserve current value
                existing.category = setting_data["category"]
                existing.value_type = setting_data["value_type"]
                existing.default_value = setting_data["default_value"]
                existing.min_value = setting_data["min_value"]
                existing.max_value = setting_data["max_value"]
                existing.allowed_values = setting_data["allowed_values"]
                existing.label = setting_data["label"]
                existing.description = setting_data["description"]
                existing.requires_restart = setting_data["requires_restart"]
                existing.display_order = setting_data["display_order"]
                updated += 1
            else:
                # Insert new setting
                new_setting = SystemSetting(
                    id=uuid4(),
                    category=setting_data["category"],
                    key=setting_data["key"],
                    value=setting_data["value"],
                    value_type=setting_data["value_type"],
                    default_value=setting_data["default_value"],
                    min_value=setting_data["min_value"],
                    max_value=setting_data["max_value"],
                    allowed_values=setting_data["allowed_values"],
                    label=setting_data["label"],
                    description=setting_data["description"],
                    requires_restart=setting_data["requires_restart"],
                    display_order=setting_data["display_order"],
                )
                session.add(new_setting)
                inserted += 1

        await session.commit()
        print(f"System settings seeded: {inserted} inserted, {updated} updated")

    await engine.dispose()


async def main():
    """Main entry point for seeding."""
    import os
    db_url = os.environ.get("DATABASE_URL")
    await seed_system_settings(db_url)


if __name__ == "__main__":
    asyncio.run(main())
