"""
Script de migración para arreglar service_ids huérfanos en citas.

Este script:
1. Obtiene los service_ids actuales (aleatorios) de los servicios en BD
2. Genera los nuevos UUIDs determinísticos basados en nombre
3. Crea un mapeo: UUID-antiguo → UUID-nuevo
4. Actualiza todas las citas con los nuevos service_ids

Ejecutar con:
    DATABASE_URL="postgresql+asyncpg://..." ./venv/bin/python -m database.scripts.fix_orphaned_service_ids

IMPORTANTE: Hacer backup de la base de datos antes de ejecutar.
"""

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select, text, update

from database.connection import get_async_session
from database.models import Appointment, Service
from database.seeds.services import ALL_SERVICES, generate_service_uuid

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def fix_orphaned_service_ids() -> None:
    """
    Migra los service_ids de citas antiguas a los nuevos UUIDs determinísticos.
    """
    logger.info("=" * 60)
    logger.info("MIGRACIÓN DE SERVICE_IDS HUÉRFANOS")
    logger.info("=" * 60)

    async with get_async_session() as session:
        # Paso 1: Obtener todos los servicios actuales y crear mapeo por nombre
        logger.info("\n1. Obteniendo servicios actuales de la BD...")
        result = await session.execute(select(Service))
        current_services = result.scalars().all()

        # Mapeo: nombre → UUID actual
        current_name_to_uuid: dict[str, UUID] = {s.name: s.id for s in current_services}
        logger.info(f"   Encontrados {len(current_services)} servicios en BD")

        # Paso 2: Generar mapeo de UUIDs antiguos a nuevos
        logger.info("\n2. Generando mapeo de UUIDs antiguos → nuevos...")
        old_to_new_uuid: dict[UUID, UUID] = {}

        for name, old_uuid in current_name_to_uuid.items():
            new_uuid = generate_service_uuid(name)
            if old_uuid != new_uuid:
                old_to_new_uuid[old_uuid] = new_uuid
                logger.info(f"   {name}:")
                logger.info(f"     Antiguo: {old_uuid}")
                logger.info(f"     Nuevo:   {new_uuid}")

        if not old_to_new_uuid:
            logger.info("   No hay UUIDs que migrar - todos ya son determinísticos")

        # Paso 3: Obtener todas las citas
        logger.info("\n3. Obteniendo citas para actualizar...")
        result = await session.execute(select(Appointment))
        appointments = result.scalars().all()
        logger.info(f"   Encontradas {len(appointments)} citas")

        # Paso 4: Actualizar service_ids en citas
        logger.info("\n4. Actualizando service_ids en citas...")
        updated_count = 0
        orphan_count = 0

        for appointment in appointments:
            if not appointment.service_ids:
                continue

            new_service_ids = []
            needs_update = False

            for old_sid in appointment.service_ids:
                if old_sid in old_to_new_uuid:
                    # UUID antiguo encontrado, usar el nuevo
                    new_service_ids.append(old_to_new_uuid[old_sid])
                    needs_update = True
                else:
                    # UUID no está en el mapeo, mantenerlo
                    new_service_ids.append(old_sid)

            if needs_update:
                # Actualizar usando SQL raw para evitar problemas con arrays
                await session.execute(
                    update(Appointment)
                    .where(Appointment.id == appointment.id)
                    .values(service_ids=new_service_ids)
                )
                updated_count += 1
                logger.info(f"   Cita {appointment.id}: actualizada")

        # Paso 5: Actualizar los servicios con UUIDs determinísticos
        logger.info("\n5. Actualizando servicios con UUIDs determinísticos...")
        services_updated = 0

        for service_data in ALL_SERVICES:
            new_uuid = generate_service_uuid(service_data["name"])

            # Buscar servicio por nombre
            result = await session.execute(
                select(Service).where(Service.name == service_data["name"])
            )
            service = result.scalar_one_or_none()

            if service and service.id != new_uuid:
                # Crear nuevo servicio con UUID determinístico
                new_service = Service(
                    id=new_uuid,
                    name=service_data["name"],
                    category=service_data["category"],
                    duration_minutes=service_data["duration_minutes"],
                    description=service_data.get("description"),
                    is_active=True,
                )

                # Eliminar el servicio antiguo
                await session.delete(service)
                await session.flush()

                # Agregar el nuevo
                session.add(new_service)
                services_updated += 1
                logger.info(f"   Servicio '{service_data['name']}': UUID actualizado")

        await session.commit()

        # Resumen
        logger.info("\n" + "=" * 60)
        logger.info("RESUMEN DE MIGRACIÓN")
        logger.info("=" * 60)
        logger.info(f"Citas actualizadas: {updated_count}")
        logger.info(f"Servicios con UUID actualizado: {services_updated}")
        logger.info("=" * 60)

        # Verificación final
        logger.info("\n6. Verificación final...")
        result = await session.execute(
            text("""
                SELECT COUNT(*) as count
                FROM appointments a
                WHERE EXISTS (
                    SELECT 1 FROM unnest(a.service_ids) sid
                    WHERE NOT EXISTS (SELECT 1 FROM services s WHERE s.id = sid)
                )
            """)
        )
        orphan_appointments = result.scalar()
        if orphan_appointments and orphan_appointments > 0:
            logger.warning(f"ADVERTENCIA: Aún hay {orphan_appointments} citas con service_ids huérfanos")
        else:
            logger.info("✓ No hay citas con service_ids huérfanos")


if __name__ == "__main__":
    asyncio.run(fix_orphaned_service_ids())
