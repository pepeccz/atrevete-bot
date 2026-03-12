"""delete_and_recreate_services_catalog

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2025-03-11 00:00:00.000000

"""
from typing import Sequence, Union
from uuid import UUID
import hashlib

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision: str = 'p6q7r8s9t0u1'
down_revision: Union[str, None] = 'o5p6q7r8s9t0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Namespace for deterministic UUID generation (must match database/seeds/services.py)
SERVICE_UUID_NAMESPACE = "atrevete-peluqueria-services"


def generate_service_uuid(service_name: str) -> str:
    """Generate deterministic UUID based on service name."""
    combined = f"{SERVICE_UUID_NAMESPACE}:{service_name}"
    hash_bytes = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return hash_bytes[:32]


# New services catalog from PDF (77 services total)
# HAIRDRESSING services (36)
HAIRDRESSING_SERVICES = [
    {"name": "Óleo Pigmento", "duration_minutes": 30, "description": "Tratamiento regulador de la porosidad capilar que equilibra el pH y mejora la salud del cabello"},
    {"name": "Agua Tierra", "duration_minutes": 25, "description": "Tratamiento capilar detoxificante que purifica el cuero cabelludo y equilibra la grasa"},
    {"name": "Corte de Flequillo", "duration_minutes": 15, "description": "Corte y modelado del flequillo para renovar tu look rápidamente"},
    {"name": "Perilla", "duration_minutes": 10, "description": "Arreglo de la perilla (patillas) para un look limpio y pulcro"},
    {"name": "Tratamiento Precolor", "duration_minutes": 5, "description": "Tratamiento previo al color que prepara el cabello para un mejor resultado"},
    {"name": "Infoactivo Fuerza", "duration_minutes": 30, "description": "Tratamiento fortalecedor que activa la fuerza capilar desde la raíz"},
    {"name": "Infoactivo Sensitivo", "duration_minutes": 30, "description": "Tratamiento específico para cabellos sensibles o irritados que calma y protege"},
    {"name": "Mechas Localizadas", "duration_minutes": 20, "description": "Mechas en zonas específicas para aportar luz y dimensión al cabello"},
    {"name": "Color Caballero", "duration_minutes": 30, "description": "Servicio de coloración específico para cabellos masculinos"},
    {"name": "Moldeado", "duration_minutes": 50, "description": "Moldeado capilar con productos profesionales para dar forma y textura al cabello"},
    {"name": "Recogido", "duration_minutes": 60, "description": "Peinado recogido elegante para eventos y ocasiones especiales"},
    {"name": "Semirecogido", "duration_minutes": 40, "description": "Peinado semirecogido que combina elegancia con un toque natural"},
    {"name": "Recogido Novia", "duration_minutes": 120, "description": "Peinado de novia completo con prueba y ejecución el día de la boda"},
    {"name": "Corte Bebé", "duration_minutes": 20, "description": "Corte capilar suave y rápido para los más pequeños de la casa"},
    {"name": "Mechas", "duration_minutes": 60, "description": "Servicio completo de mechas para iluminar y dar dimensión al cabello"},
    {"name": "Mechas Extras", "duration_minutes": 70, "description": "Servicio de mechas extendido para cabellos largos o con mucha densidad"},
    {"name": "Barro Gold", "duration_minutes": 40, "description": "Tratamiento de coloración con barro que nutre mientras aporta tonos dorados"},
    {"name": "Mechas Localizadas Express", "duration_minutes": 15, "description": "Versión express de mechas localizadas para un toque de luz rápido"},
    {"name": "Óleo Extra", "duration_minutes": 40, "description": "Tratamiento intensivo con óleos esenciales para cabello muy dañado o seco"},
    {"name": "Barro Extra", "duration_minutes": 40, "description": "Tratamiento de barro intensivo para cabellos que necesitan nutrición profunda"},
    {"name": "Barba", "duration_minutes": 15, "description": "Arreglo y modelado de barba para un look cuidado y masculino"},
    {"name": "Moldeado Extra", "duration_minutes": 70, "description": "Moldeado extendido para cabellos largos o con tratamientos químicos previos"},
    {"name": "Agua Lluvia", "duration_minutes": 25, "description": "Tratamiento hidratante que aporta brillo y suavidad como la lluvia fresca"},
    {"name": "Cultura de Color Extra", "duration_minutes": 50, "description": "Servicio de coloración extendido para cambios drásticos o correcciones"},
    {"name": "Prepigmentar", "duration_minutes": 10, "description": "Proceso de prepigmentación para preparar el cabello antes de ciertos colores"},
    {"name": "Cortar", "duration_minutes": 40, "description": "Corte capilar completo con lavado incluido"},
    {"name": "Peinado Largo", "duration_minutes": 45, "description": "Peinado profesional para cabello largo, incluye lavado ritual facial"},
    {"name": "Barro", "duration_minutes": 40, "description": "Tratamiento de coloración con barro natural que nutre el cabello"},
    {"name": "Peinado Extra", "duration_minutes": 70, "description": "Peinado extendido para cabello muy largo o elaborado"},
    {"name": "Corte Niña", "duration_minutes": 30, "description": "Corte especializado para niñas con técnicas adaptadas a su edad"},
    {"name": "Cultura de Color", "duration_minutes": 40, "description": "Servicio de coloración profesional con productos de alta calidad"},
    {"name": "Peinado Niña Comunión", "duration_minutes": 70, "description": "Peinado elegante para niñas en su Primera Comunión"},
    {"name": "Secado", "duration_minutes": 20, "description": "Secado profesional del cabello para un acabado pulcro"},
    {"name": "Peinado", "duration_minutes": 40, "description": "Peinado profesional para el día a día o eventos informales"},
    {"name": "Corte Niño", "duration_minutes": 30, "description": "Corte especializado para niños con técnicas adaptadas a su edad"},
    {"name": "Corte Caballero", "duration_minutes": 40, "description": "Corte capilar completo para caballeros con lavado incluido"},
]

# AESTHETICS services (41)
AESTHETICS_SERVICES = [
    {"name": "Masaje Corporal (60 min)", "duration_minutes": 60, "description": "Masaje corporal relajante de cuerpo completo para aliviar tensiones y estrés acumulado"},
    {"name": "Maquillaje", "duration_minutes": 60, "description": "Servicio de maquillaje profesional para eventos, fiestas y ocasiones especiales"},
    {"name": "Tinte de Pestañas", "duration_minutes": 40, "description": "Tratamiento para dar color oscuro y duradero a las pestañas naturales"},
    {"name": "Peeling Corporal", "duration_minutes": 60, "description": "Exfoliación corporal profunda que renueva la piel eliminando células muertas"},
    {"name": "Tinte + Permanente de Pestañas", "duration_minutes": 90, "description": "Tratamiento combinado que da color y curvatura natural duradera a las pestañas"},
    {"name": "Permanente de Pestañas", "duration_minutes": 40, "description": "Tratamiento para dar curvatura natural y duradera a las pestañas sin necesidad de rizador"},
    {"name": "Bioterapia Facial + Radiofrecuencia (30 min)", "duration_minutes": 90, "description": "Tratamiento facial avanzado combinado con 30 minutos de radiofrecuencia para resultados anti-edad potenciados"},
    {"name": "Bioterapia Facial + Radiofrecuencia (15 min)", "duration_minutes": 75, "description": "Tratamiento facial combinado con 15 minutos de radiofrecuencia para rejuvenecimiento facial"},
    {"name": "Bioterapia Facial", "duration_minutes": 60, "description": "Tratamiento facial personalizado según las necesidades específicas de tu piel"},
    {"name": "Maquillaje Express", "duration_minutes": 30, "description": "Maquillaje rápido y profesional para el día a día o eventos informales"},
    {"name": "Brazos Completos o Pecho", "duration_minutes": 30, "description": "Depilación con cera de brazos completos o zona del pecho"},
    {"name": "Higiene de Espalda", "duration_minutes": 60, "description": "Limpieza facial especializada para la espalda, ideal para tratar impurezas y acné"},
    {"name": "Maquillaje Novia", "duration_minutes": 70, "description": "Maquillaje profesional para novias con prueba previa y duración todo el evento"},
    {"name": "Cejas", "duration_minutes": 15, "description": "Depilación con cera y diseño de cejas para enmarcar la mirada"},
    {"name": "Ingles o Axilas", "duration_minutes": 30, "description": "Depilación con cera de la zona de ingles o axilas"},
    {"name": "Manicura Permanente + Bio", "duration_minutes": 90, "description": "Manicura con esmalte permanente combinado con tratamiento bioterapéutico para manos"},
    {"name": "Bioterapia Sculptor + Radiofrecuencia 30 min", "duration_minutes": 90, "description": "Tratamiento corporal anticelulítico combinado con 30 minutos de radiofrecuencia para resultados potenciados"},
    {"name": "Limar y Pintar Manos Permanente", "duration_minutes": 40, "description": "Servicio de limado y esmaltado permanente de uñas de manos"},
    {"name": "Brazos Medios", "duration_minutes": 30, "description": "Depilación con cera de media brazo (antebrazo o parte superior)"},
    {"name": "Bioterapia de Senos", "duration_minutes": 60, "description": "Tratamiento que aumenta naturalmente el volumen del seno mejorando hidratación y tonicidad"},
    {"name": "Masaje Corporal (30 min)", "duration_minutes": 30, "description": "Masaje corporal relajante de 30 minutos para aliviar tensiones específicas"},
    {"name": "Bono Bioterapia de Senos", "duration_minutes": 60, "description": "Bono de sesiones de bioterapia de senos con precio especial"},
    {"name": "Quita Esmalte Permanente", "duration_minutes": 25, "description": "Servicio de retirada de esmalte permanente de uñas"},
    {"name": "Medios Brazos", "duration_minutes": 20, "description": "Depilación con cera de media brazo (antebrazo o parte superior)"},
    {"name": "Piernas Perfectas + Presoterapia (30 min)", "duration_minutes": 90, "description": "Tratamiento combinado que drena toxinas, descongestiona y reafirma las piernas"},
    {"name": "Cera Enteras", "duration_minutes": 40, "description": "Depilación con cera de piernas enteras"},
    {"name": "Cera Medias Piernas", "duration_minutes": 30, "description": "Depilación con cera de medias piernas"},
    {"name": "Abdomen, Glúteos, Espalda o Pecho", "duration_minutes": 30, "description": "Depilación con cera de una zona a elegir: abdomen, glúteos, espalda o pecho"},
    {"name": "Cera Muslos", "duration_minutes": 30, "description": "Depilación con cera de la zona de los muslos"},
    {"name": "Pubis Completo", "duration_minutes": 30, "description": "Depilación con cera de la zona del pubis completo"},
    {"name": "Ingles Brasileñas", "duration_minutes": 30, "description": "Depilación con cera de la zona de ingles al estilo brasileño"},
    {"name": "Barro Gold Extra", "duration_minutes": 40, "description": "Tratamiento facial con barro dorado de alta gama para nutrición profunda"},
    {"name": "Bioterapia Sculptor Completo", "duration_minutes": 60, "description": "Tratamiento corporal anticelulítico completo que reduce nódulos grasos y retención de líquidos"},
    {"name": "Bioterapia Podal", "duration_minutes": 40, "description": "Tratamiento específico para pies cansados y fatigados que hidrata y revitaliza"},
    {"name": "Limar y Pintar Pies", "duration_minutes": 30, "description": "Servicio básico de limado y esmaltado de uñas de pies"},
    {"name": "Limar y Pintar Pies Permanente", "duration_minutes": 40, "description": "Servicio de limado y esmaltado permanente de uñas de pies"},
    {"name": "Bioterapia de Manos", "duration_minutes": 45, "description": "Tratamiento específico para hidratar, rejuvenecer y cuidar las manos"},
    {"name": "Pedicura Permanente con Bioterapia", "duration_minutes": 75, "description": "Pedicura completa con esmalte permanente y tratamiento bioterapéutico para pies"},
    {"name": "Manicura Caballero", "duration_minutes": 30, "description": "Manicura profesional para caballeros con limado, cutículas e hidratación"},
    {"name": "Limar y Pintar Manos", "duration_minutes": 30, "description": "Servicio básico de limado y esmaltado de uñas de manos"},
    {"name": "Labio", "duration_minutes": 10, "description": "Depilación con cera del labio superior o inferior"},
]


# Combine all services
ALL_SERVICES = HAIRDRESSING_SERVICES + AESTHETICS_SERVICES


def get_new_service_names() -> set:
    """Get set of new service names from PDF catalog."""
    return {svc["name"] for svc in ALL_SERVICES}


def get_new_service_uuids() -> set:
    """Get set of deterministic UUIDs for new services."""
    return {generate_service_uuid(svc["name"]) for svc in ALL_SERVICES}


def upgrade() -> None:
    """
    Delete old services and recreate catalog from PDF.
    
    Steps:
    1. Capture current service IDs and names
    2. Identify appointments that will be orphaned
    3. Delete orphaned appointments (those with only old services)
    4. Delete old services
    5. Insert new services from PDF with deterministic UUIDs
    6. Verify no orphaned appointments remain
    """
    conn = op.get_bind()
    
    # =========================================================================
    # Step 1: Capture current state
    # =========================================================================
    print("→ Step 1: Capturing current services...")
    
    result = conn.execute(text("""
        SELECT id, name FROM services ORDER BY name
    """))
    old_services = {row[0]: row[1] for row in result.fetchall()}
    old_service_count = len(old_services)
    print(f"  Found {old_service_count} existing services")
    
    # =========================================================================
    # Step 2: Identify new service UUIDs
    # =========================================================================
    new_service_names = get_new_service_names()
    new_service_uuids = get_new_service_uuids()
    print(f"  New catalog has {len(new_service_names)} services")
    
    # =========================================================================
    # Step 3: Find appointments that will be orphaned
    # =========================================================================
    print("→ Step 2: Identifying orphaned appointments...")
    
    # Get all appointments with their service_ids
    result = conn.execute(text("""
        SELECT id, service_ids, first_name, last_name 
        FROM appointments 
        WHERE service_ids IS NOT NULL AND array_length(service_ids, 1) > 0
    """))
    appointments = result.fetchall()
    
    orphaned_appointments = []
    for apt_id, service_ids, first_name, last_name in appointments:
        if service_ids:
            # Check if ANY service_id in this appointment will still exist
            has_valid_service = any(
                str(sid) in new_service_uuids for sid in service_ids
            )
            if not has_valid_service:
                customer_name = f"{first_name} {last_name}".strip() if first_name else "Unknown"
                orphaned_appointments.append({
                    "id": apt_id,
                    "customer": customer_name,
                    "service_ids": service_ids
                })
    
    print(f"  Found {len(orphaned_appointments)} appointments to delete")
    
    # =========================================================================
    # Step 4: Delete orphaned appointments
    # =========================================================================
    print("→ Step 3: Deleting orphaned appointments...")
    
    deleted_count = 0
    for apt in orphaned_appointments:
        conn.execute(
            text("DELETE FROM appointments WHERE id = :id"),
            {"id": apt["id"]}
        )
        deleted_count += 1
    
    print(f"  Deleted {deleted_count} appointments")
    
    # =========================================================================
    # Step 5: Delete old services (not in new catalog)
    # =========================================================================
    print("→ Step 4: Deleting old services...")
    
    # Delete services whose names are NOT in the new catalog
    deleted_services = []
    for svc_id, svc_name in old_services.items():
        if svc_name not in new_service_names:
            conn.execute(
                text("DELETE FROM services WHERE id = :id"),
                {"id": svc_id}
            )
            deleted_services.append(svc_name)
    
    print(f"  Deleted {len(deleted_services)} old services")
    
    # =========================================================================
    # Step 6: Insert new services (with deterministic UUIDs)
    # =========================================================================
    print("→ Step 5: Inserting new services from PDF catalog...")
    
    inserted_count = 0
    updated_count = 0
    
    for svc in ALL_SERVICES:
        svc_uuid = generate_service_uuid(svc["name"])
        category = "HAIRDRESSING" if svc in HAIRDRESSING_SERVICES else "AESTHETICS"
        
        # Check if service already exists (by UUID)
        result = conn.execute(
            text("SELECT id FROM services WHERE id = :id"),
            {"id": svc_uuid}
        )
        exists = result.fetchone() is not None
        
        if exists:
            # Update existing service
            conn.execute(
                text("""
                    UPDATE services 
                    SET name = :name, 
                        category = :category, 
                        duration_minutes = :duration_minutes,
                        description = :description,
                        is_active = true,
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {
                    "id": svc_uuid,
                    "name": svc["name"],
                    "category": category,
                    "duration_minutes": svc["duration_minutes"],
                    "description": svc["description"]
                }
            )
            updated_count += 1
        else:
            # Insert new service
            conn.execute(
                text("""
                    INSERT INTO services (id, name, category, duration_minutes, description, is_active, created_at, updated_at)
                    VALUES (:id, :name, :category, :duration_minutes, :description, true, NOW(), NOW())
                """),
                {
                    "id": svc_uuid,
                    "name": svc["name"],
                    "category": category,
                    "duration_minutes": svc["duration_minutes"],
                    "description": svc["description"]
                }
            )
            inserted_count += 1
    
    print(f"  Inserted: {inserted_count} new services")
    print(f"  Updated: {updated_count} existing services")
    
    # =========================================================================
    # Step 7: Verify no orphaned appointments remain
    # =========================================================================
    print("→ Step 6: Verifying no orphaned appointments remain...")
    
    result = conn.execute(text("""
        SELECT id, service_ids 
        FROM appointments 
        WHERE service_ids IS NOT NULL AND array_length(service_ids, 1) > 0
    """))
    remaining_appointments = result.fetchall()
    
    orphaned_remaining = 0
    for apt_id, service_ids in remaining_appointments:
        if service_ids:
            for sid in service_ids:
                result = conn.execute(
                    text("SELECT id FROM services WHERE id = :id"),
                    {"id": sid}
                )
                if not result.fetchone():
                    orphaned_remaining += 1
                    print(f"  WARNING: Appointment {apt_id} references orphaned service {sid}")
    
    if orphaned_remaining == 0:
        print("  ✓ No orphaned appointments found")
    else:
        print(f"  ⚠ {orphaned_remaining} orphaned service references found")
    
    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "="*60)
    print("MIGRATION SUMMARY")
    print("="*60)
    print(f"Old services deleted: {len(deleted_services)}")
    print(f"Appointments deleted: {deleted_count}")
    print(f"New services inserted: {inserted_count}")
    print(f"Existing services updated: {updated_count}")
    print(f"Total services after migration: {inserted_count + updated_count}")
    print("="*60)


def downgrade() -> None:
    """
    Downgrade is NOT supported for this migration.
    
    This migration permanently deletes data (old services and orphaned appointments).
    To restore the previous state, you MUST restore from a database backup taken
    before running this migration.
    
    This function intentionally raises an exception to prevent accidental downgrade.
    """
    raise Exception(
        "DOWNGRADE NOT SUPPORTED: This migration permanently deletes old services "
        "and appointments referencing them. To restore the previous state, "
        "restore from a database backup taken before running this migration. "
        "\n\n"
        "If you really need to rollback, manually:\n"
        "1. Restore from backup\n"
        "2. Or manually recreate the old services and re-link appointments"
    )
