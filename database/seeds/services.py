"""
Seed data script for services table - VERSIÓN DEFINITIVA desde data/Services.csv

Este archivo contiene los 69 servicios oficiales de Atrévete Peluquería:
- 27 servicios de Peluquería
- 42 servicios de Estética

Datos y descripciones actualizados desde atrevetepeluqueria.com (2024-12).
Can be run standalone: python -m database.seeds.services
"""

import asyncio

from sqlalchemy import select

from database.connection import get_async_session
from database.models import Service, ServiceCategory

# ============================================================================
# SERVICIOS DE PELUQUERÍA (27 servicios)
# ============================================================================

HAIRDRESSING_SERVICES = [
    # --- TRATAMIENTO + PEINADO ---
    {
        "name": "Tratamiento + Peinado Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Tratamientos personalizado, lavado dermocapila, ritual facial y peinado",
    },
    {
        "name": "Tratamiento + Peinado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 90,
        "description": "Tratamientos personalizado, lavado dermocapilar,ritual facial y peinado",
    },
    {
        "name": "Tratamiento + Peinado corto/medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "tratamientos personalizado, lavado dermocapilar,ritual facial y peinado",
    },

    # --- PEINADO ---
    {
        "name": "Peinado Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Lavado dermo capilar,ritual facial y peinado",
    },
    {
        "name": "Peinado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 90,
        "description": "Lavado dermo capilar,ritual facial y peinado",
    },
    {
        "name": "Peinado Corto - Medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Lavado dermo capilar,ritual facial y peinado",
    },

    # --- PACK ÓLEO PIGMENTO + PEINADO ---
    {
        "name": "Pack Óleo Pigmento + Peinado Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Óleo Pigmento + Peinado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 150,
        "description": "regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Óleo Pigmento + Peinado Corto - Medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },

    # --- PACK MOLDEADO ---
    {
        "name": "Pack Moldeado Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 150,
        "description": "regulador de la porosidad, servicio de moldeado, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Moldeado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 150,
        "description": "regulador de la porosidad, servicio de moldeado, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Moldeado Corto - Medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "regulador de la porosidad, servicio de moldeado, equibrador del Ph, ritual facial y peinado",
    },

    # --- PACK MECHAS ---
    {
        "name": "Pack Mechas Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 180,
        "description": "regulador de la porosidad, servicio de mechas, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Mechas Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 210,
        "description": "regulador de la porosidad, servicio de mechas, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Mechas Corto - Medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 180,
        "description": "regulador de la porosidad, servicio de mechas, equibrador del Ph, ritual facial y peinado",
    },

    # --- PACK DUAL: MECHAS + COLOR ---
    {
        "name": "Pack Dual: Mechas + Color Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 180,
        "description": "regulador de la porosidad, servicio dual, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Dual: Mechas + Color Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 210,
        "description": "regulador de la porosidad, servicio dual, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Dual: Mechas + Color Corto - Medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 180,
        "description": "regulador de la porosidad, servicio dual, equibrador del Ph, ritual facial y peinado",
    },

    # --- PACK CULTURA DE COLOR ---
    {
        "name": "Pack cultura de Color Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Cultura de Color Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 150,
        "description": "Regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack cultura de Color Corto - Medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },

    # --- PACK BARRO GOLD ---
    {
        "name": "Pack Barro Gold Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Barro Gold Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 150,
        "description": "Regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },
    {
        "name": "Pack Barro Gold Corto - Medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Regulador de la porosidad, servicio de color, equibrador del Ph, ritual facial y peinado",
    },

    # --- CORTE + PEINADO ---
    {
        "name": "Corte + Peinado Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Lavado dermo capilar, ritual facial  corte y peinado",
    },
    {
        "name": "Corte + Peinado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Lavado dermo capilar, ritual facial corte y peinado",
    },
    {
        "name": "Corte + Peinado Corto - Medio",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Lavado dermo capilar, ritual facial y cortar peinado",
    },
]

# ============================================================================
# SERVICIOS DE ESTÉTICA (42 servicios)
# ============================================================================

AESTHETICS_SERVICES = [
    # --- PESTAÑAS ---
    {
        "name": "Tinte de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento para dar color a las pestañas de forma duradera",
    },
    {
        "name": "Tinte + Permanente de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 150,
        "description": "Tratamiento combinado para dar color y curvatura a las pestañas",
    },
    {
        "name": "Permanente de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento para dar curvatura natural y duradera a las pestañas",
    },

    # --- CORPORAL ---
    {
        "name": "Peeling Corporal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Exfoliación corporal profunda para renovar y suavizar la piel",
    },
    {
        "name": "Masaje 60 min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Masaje corporal relajante de 60 minutos para aliviar tensiones y estrés",
    },
    {
        "name": "Masaje 30 min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Masaje corporal relajante de 30 minutos para aliviar tensiones",
    },
    {
        "name": "Higiene de Espalda",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Limpieza especializada y profunda de la zona de la espalda",
    },

    # --- MAQUILLAJE ---
    {
        "name": "Maquillaje",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Servicio de maquillaje profesional para eventos y ocasiones especiales",
    },

    # --- MANICURA ---
    {
        "name": "Manicura Permanente + Bioterapia de Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Servicio de manicura con esmalte permanente y tratamiento hidratante para manos",
    },
    {
        "name": "Limar + Pintar Uñas de las Manos Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Servicio de limado y esmaltado permanente de uñas de las manos",
    },
    {
        "name": "Limar + Pintar Uñas de las Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Servicio básico de limado y esmaltado de uñas de las manos",
    },

    # --- PEDICURA ---
    {
        "name": "Pedicura Permanente + Bioterapia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Servicio de pedicura con esmalte permanente y tratamiento hidratante para pies",
    },
    {
        "name": "Limar + Pintar Uñas de los Pies Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Servicio de limado y esmaltado permanente de uñas de los pies",
    },
    {
        "name": "Limar + Pintar Uñas de los Pies",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Servicio básico de limado y esmaltado de uñas de los pies",
    },

    # --- DEPILACIÓN ---
    {
        "name": "Depilación Pubis Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona del pubis completo",
    },
    {
        "name": "Depilación Piernas Enteras",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Depilación con cera de las piernas completas",
    },
    {
        "name": "Depilación Pecho",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona del pecho",
    },
    {
        "name": "Depilación Muslos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de los muslos",
    },
    {
        "name": "Depilación Medias Piernas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de las medias piernas",
    },
    {
        "name": "Depilación Lumbar",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona lumbar",
    },
    {
        "name": "Depilación Labios",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera del labio superior",
    },
    {
        "name": "Depilación Ingles Brasileñas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de ingles estilo brasileño",
    },
    {
        "name": "Depilación Ingles",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de las ingles",
    },
    {
        "name": "Depilación Glúteos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de los glúteos",
    },
    {
        "name": "Depilación Espalda",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de la espalda",
    },
    {
        "name": "Depilación Cejas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera para dar forma a las cejas",
    },
    {
        "name": "Depilación Brazos Completos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de los brazos completos",
    },
    {
        "name": "Depilación Brazo Medio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de medio brazo",
    },
    {
        "name": "Depilación Axilas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de las axilas",
    },
    {
        "name": "Depilación Abdomen",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona del abdomen",
    },

    # --- BIOTERAPIA FACIAL ---
    {
        "name": "Bioterapia Vitalizadora",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento facial para generar vitalidad y energía a nivel celular. Alisa la piel, reduce arrugas, minimiza poros y aporta elasticidad",
    },
    {
        "name": "Bioterapia Sensitiva",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento que refuerza la función protectora de la piel en casos sensibles o irritados. Calma, hidrata y equilibra el tono cutáneo",
    },
    {
        "name": "Bioterapia Iluminante",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Reduce o elimina manchas cutáneas de forma progresiva. Aclara pieles oscurecidas y regula la melanina",
    },
    {
        "name": "Bioterapia Detox",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Reequilibra los desórdenes provocados por exceso de grasa y deshidratación. Depura toxinas, regula seborrea y oxigena la piel",
    },

    # --- BIOTERAPIA + RADIOFRECUENCIA ---
    {
        "name": "Bioterapia + Radiofrecuencia 30 min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento facial combinado con radiofrecuencia de 30 minutos para potenciar resultados anti-edad",
    },
    {
        "name": "Bioterapia + Radiofrecuencia 15 min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento facial combinado con radiofrecuencia de 15 minutos para potenciar resultados anti-edad",
    },

    # --- BIOTERAPIA CORPORAL ---
    {
        "name": "Bioterapia Sculptor Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Reduce visiblemente los nódulos grasos de la celulitis. Estiliza la figura y minimiza la retención de líquidos",
    },
    {
        "name": "Bioterapia Sculptor + Radiofrecuencia 30 min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento anticelulítico combinado con radiofrecuencia de 30 minutos para potenciar resultados",
    },
    {
        "name": "Bioterapia Piernas Perfectas + Presoterapia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Drena toxinas, descongestiona, calma y reafirma las piernas combinando bioterapia con presoterapia",
    },
    {
        "name": "Bioterapia de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Aumenta de forma natural y progresiva el volumen del seno mejorando la hidratación e impulso energético",
    },
    {
        "name": "Bioterapia Podal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento específico para pies cansados y fatigados. Hidrata y revitaliza",
    },
    {
        "name": "Bioterapia de Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Tratamiento específico para hidratar y rejuvenecer las manos",
    },
]

# Consolidar todos los servicios
ALL_SERVICES = HAIRDRESSING_SERVICES + AESTHETICS_SERVICES


async def seed_services() -> None:
    """
    Seed services table with the 69 official services from data/Services.csv.

    DESTRUCTIVE: Deletes all existing services and replaces with the catalog.
    This ensures the database matches exactly the CSV file.
    """
    async with get_async_session() as session:
        from sqlalchemy import delete

        # Step 1: Delete ALL existing services
        delete_stmt = delete(Service)
        result = await session.execute(delete_stmt)
        deleted_count = result.rowcount

        # Step 2: Insert all services from catalog
        for service_data in ALL_SERVICES:
            service = Service(**service_data)
            session.add(service)

        await session.commit()

        # Statistics
        total_services = len(ALL_SERVICES)
        total_hair = len(HAIRDRESSING_SERVICES)
        total_aesthetics = len(AESTHETICS_SERVICES)

        print(f"✓ Services seed completed:")
        print(f"  - Deleted: {deleted_count} old services")
        print(f"  - Created: {total_services} new services")
        print(f"  - Peluquería: {total_hair}")
        print(f"  - Estética: {total_aesthetics}")


if __name__ == "__main__":
    asyncio.run(seed_services())
