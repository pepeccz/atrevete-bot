"""
Seed data script for services table - VERSIÓN NUEVA basada en atrevetepeluqueria.com

Este archivo reemplaza el anterior services.py con los servicios reales de la web.
- Solo categorías: Peluquería y Estética
- Servicios con variaciones de precio → entradas separadas
- Sin bonos 5+1 (solo sesiones individuales)
- Sin servicios de novia

Populates ~80 services from atrevetepeluqueria.com
Can be run standalone: python -m database.seeds.services_nuevo
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select

from database.connection import get_async_session
from database.models import Service, ServiceCategory

# ============================================================================
# SERVICIOS DE PELUQUERÍA
# ============================================================================

HAIRDRESSING_SERVICES = [
    # --- PEINADOS ---
    {
        "name": "Peinado (Corto-Medio)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Peinado profesional con secado que incluye lavado dermocapilar, ritual facial y acabado perfecto para cabello corto o medio.",
    },
    {
        "name": "Peinado (Largo)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 45,
        "description": "Peinado profesional con secado que incluye lavado dermocapilar, ritual facial y acabado perfecto para cabello largo.",
    },
    {
        "name": "Peinado (Extra)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Peinado profesional con secado que incluye lavado dermocapilar, ritual facial y acabado perfecto para cabello extra largo o elaborado.",
    },

    # --- CORTE + PEINADO ---
    {
        "name": "Corte + Peinado (Corto-Medio)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Servicio completo de corte y peinado con lavado dermocapilar, ritual facial, corte profesional y acabado con secado para cabello corto o medio.",
    },
    {
        "name": "Corte + Peinado (Largo)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Servicio completo de corte y peinado con lavado dermocapilar, ritual facial, corte profesional y acabado con secado para cabello largo.",
    },
    {
        "name": "Corte + Peinado (Extra)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 80,
        "description": "Servicio completo de corte y peinado con lavado dermocapilar, ritual facial, corte profesional y acabado con secado para cabello extra largo.",
    },

    # --- TRATAMIENTO + PEINADO ---
    {
        "name": "Tratamiento + Peinado (Corto-Medio)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Tratamiento personalizado (Agua de Lluvia, Agua de Tierra, Infoactivos) con peinado profesional para cabello corto o medio. Atiende necesidades específicas del cabello.",
    },
    {
        "name": "Tratamiento + Peinado (Largo)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Tratamiento personalizado (Agua de Lluvia, Agua de Tierra, Infoactivos) con peinado profesional para cabello largo. Atiende necesidades específicas del cabello.",
    },
    {
        "name": "Tratamiento + Peinado (Extra)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 80,
        "description": "Tratamiento personalizado (Agua de Lluvia, Agua de Tierra, Infoactivos) con peinado profesional para cabello extra largo. Atiende necesidades específicas del cabello.",
    },

    # --- COLOR ÓLEO PIGMENTO + PEINADO ---
    {
        "name": "Color Óleo Pigmento + Peinado (Corto-Medio)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 90,
        "description": "Coloración semi-permanente con aceites nutritivos que protege y da brillo intenso. Incluye balanceador de pH y peinado profesional para cabello corto o medio.",
    },
    {
        "name": "Color Óleo Pigmento + Peinado (Largo)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 100,
        "description": "Coloración semi-permanente con aceites nutritivos que protege y da brillo intenso. Incluye balanceador de pH y peinado profesional para cabello largo.",
    },
    {
        "name": "Color Óleo Pigmento + Peinado (Extra)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Coloración semi-permanente con aceites nutritivos que protege y da brillo intenso. Incluye balanceador de pH y peinado profesional para cabello extra largo.",
    },

    # --- CULTURA DE COLOR ---
    {
        "name": "Cultura de Color (Corto-Medio)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 100,
        "description": "Coloración profesional completa que respeta la estructura capilar mientras aporta color vibrante y duradero para cabello corto o medio.",
    },
    {
        "name": "Cultura de Color (Largo)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 110,
        "description": "Coloración profesional completa que respeta la estructura capilar mientras aporta color vibrante y duradero para cabello largo.",
    },
    {
        "name": "Cultura de Color (Extra)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Coloración profesional completa que respeta la estructura capilar mientras aporta color vibrante y duradero para cabello extra largo.",
    },

    # --- MECHAS ---
    {
        "name": "Mechas (Corto-Medio)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Técnica de iluminación que aporta luminosidad y movimiento al cabello. Incluye regulador de porosidad y balanceador de pH para cabello corto o medio.",
    },
    {
        "name": "Mechas (Largo)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 135,
        "description": "Técnica de iluminación que aporta luminosidad y movimiento al cabello. Incluye regulador de porosidad y balanceador de pH para cabello largo.",
    },
    {
        "name": "Mechas (Extra)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 150,
        "description": "Técnica de iluminación que aporta luminosidad y movimiento al cabello. Incluye regulador de porosidad y balanceador de pH para cabello extra largo.",
    },

    # --- PACK DUAL: MECHAS + COLOR (estos son servicios combinados de la web) ---
    {
        "name": "Pack Dual: Mechas + Color (Corto-Medio)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 180,
        "description": "Servicio combinado de mechas con coloración completa. Perfecto para transformaciones de look completas para cabello corto o medio.",
    },
    {
        "name": "Pack Dual: Mechas + Color (Largo)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 195,
        "description": "Servicio combinado de mechas con coloración completa. Perfecto para transformaciones de look completas para cabello largo.",
    },
    {
        "name": "Pack Dual: Mechas + Color (Extra)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 210,
        "description": "Servicio combinado de mechas con coloración completa. Perfecto para transformaciones de look completas para cabello extra largo.",
    },

    # --- PACK MOLDEADO ---
    {
        "name": "Pack Moldeado (Corto-Medio)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 90,
        "description": "Alisado temporal con tratamientos reguladores que suaviza y moldea el cabello para un acabado sedoso y manejable para cabello corto o medio.",
    },
    {
        "name": "Pack Moldeado (Largo)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 100,
        "description": "Alisado temporal con tratamientos reguladores que suaviza y moldea el cabello para un acabado sedoso y manejable para cabello largo.",
    },
    {
        "name": "Pack Moldeado (Extra)",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Alisado temporal con tratamientos reguladores que suaviza y moldea el cabello para un acabado sedoso y manejable para cabello extra largo o muy rebelde.",
    },

    # --- SERVICIOS DE CABALLERO ---
    {
        "name": "Corte de Caballero",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Corte de cabello masculino profesional con lavado, ritual facial y acabado personalizado.",
    },
    {
        "name": "Arreglo de Barba",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Arreglo y perfilado profesional de barba para un estilo impecable.",
    },

    # --- OTROS SERVICIOS DE PELUQUERÍA DEL CSV ---
    {
        "name": "Agua Tierra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 25,
        "description": "Reconstruye la fibra capilar deteriorada restaurando las cutículas dañadas y favorece la transpiración del cuero cabelludo. Perfecto para cabellos finos y dañados.",
    },
    {
        "name": "Agua Lluvia",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 25,
        "description": "Repara el cabello dañado o deshidratado y favorece la transpiración y relajación del cuero cabelludo. Ideal para cabellos secos o deshidratados.",
    },
    {
        "name": "Infoactivo Fuerza",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Vitalizador capilar interno que reactiva y aporta vitalidad al cabello, además de regular el exceso de grasa. Tratamiento revitalizante intensivo.",
    },
    {
        "name": "Infoactivo Sensitivo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Relajante capilar que relaja y calma los casos de descamación y cuero cabelludo irritado. Ideal para pieles sensibles y reactivas.",
    },
    {
        "name": "Barro",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Mascarilla capilar purificante con minerales que elimina impurezas y aporta nutrición profunda.",
    },
    {
        "name": "Barro Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Mascarilla capilar purificante extra con minerales intensivos que elimina impurezas y aporta nutrición profunda para cabellos más exigentes.",
    },
    {
        "name": "Barro Gold",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Mascarilla capilar purificante premium con minerales gold que elimina impurezas y aporta nutrición profunda para cabellos más exigentes.",
    },
    {
        "name": "Barro Gold Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Mascarilla capilar purificante premium extra con minerales gold intensivos que elimina impurezas y aporta nutrición profunda máxima.",
    },
    {
        "name": "Óleo Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento intensivo con aceites esenciales para nutrición profunda y brillo excepcional. Versión potenciada del óleo pigmento.",
    },
    {
        "name": "Moldeado",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 50,
        "description": "Alisado temporal que suaviza y moldea el cabello para un acabado sedoso y manejable.",
    },
    {
        "name": "Moldeado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Alisado temporal extra que suaviza y moldea el cabello para un acabado sedoso y manejable. Versión para cabellos muy rebeldes.",
    },
    {
        "name": "Mechas Localizadas",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 20,
        "description": "Técnica de iluminación localizada que aporta luminosidad y movimiento al cabello en zonas específicas. Para retoques.",
    },
    {
        "name": "Corte de Flequillo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Corte de flequillo para renovar tu look de forma rápida y sencilla.",
    },
    {
        "name": "Perilla",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Arreglo y perfilado de perilla para un acabado pulido y definido.",
    },
    {
        "name": "Corte Bebé",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 20,
        "description": "Corte de cabello para bebés con cuidado especial y ambiente relajado.",
    },
    {
        "name": "Corte Niño",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Corte de cabello para niño con estilo actual y acabado cuidado.",
    },
    {
        "name": "Corte Niña",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Corte de cabello para niña con técnicas adaptadas y acabado profesional.",
    },
    {
        "name": "Secado",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 5,
        "description": "Secado básico profesional para dar forma y volumen al cabello.",
    },
    {
        "name": "Tratamiento Precolor",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 5,
        "description": "Preparación protectora del cuero cabelludo antes de coloraciones. Minimiza irritaciones y optimiza la fijación del color.",
    },
    {
        "name": "Color Caballero",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Coloración específica para cabello masculino con productos que respetan el cuero cabelludo.",
    },

    # --- CONSULTAS GRATUITAS ---
    {
        "name": "Consulta Gratuita Peluquería",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Consulta gratuita de 10 minutos para asesoramiento sobre servicios de peluquería y tratamientos capilares.",
    },
]

# ============================================================================
# SERVICIOS DE ESTÉTICA
# ============================================================================

AESTHETICS_SERVICES = [
    # --- BIOTERAPIA FACIAL (4 variantes a mismo precio) ---
    {
        "name": "Bioterapia Facial Vitalizadora",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento facial con bioterapia que genera vitalidad y energía a nivel celular. Regenera y revitaliza la piel.",
    },
    {
        "name": "Bioterapia Facial Sensitiva",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento facial con bioterapia que calma la piel sensible e irritada. Ideal para pieles reactivas.",
    },
    {
        "name": "Bioterapia Facial Iluminante",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento facial con bioterapia que reduce las manchas de la piel y aporta luminosidad.",
    },
    {
        "name": "Bioterapia Facial Detox",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento facial con bioterapia que reequilibra problemas de piel grasa y purifica en profundidad.",
    },

    # --- BIOTERAPIA FACIAL + RADIOFRECUENCIA ---
    {
        "name": "Bioterapia Facial + Radiofrecuencia 15min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Bioterapia facial potenciada con 15 minutos de radiofrecuencia para mayor efecto tensor y rejuvenecedor.",
    },
    {
        "name": "Bioterapia Facial + Radiofrecuencia 30min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Bioterapia facial completa con 30 minutos de radiofrecuencia para resultados anti-edad visibles y duraderos.",
    },

    # --- TRATAMIENTOS CORPORALES ---
    {
        "name": "Bioterapia de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento específico para la zona del busto que tonifica y mejora la firmeza de la piel.",
    },
    {
        "name": "Bioterapia Piernas Perfectas + Presoterapia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento integral para piernas con presoterapia que mejora circulación y reduce retención de líquidos.",
    },
    {
        "name": "Bioterapia Escultor Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento corporal escultor completo que reafirma y modela la silueta de forma natural.",
    },
    {
        "name": "Bioterapia Escultor + Radiofrecuencia 30min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento escultor corporal potenciado con 30 minutos de radiofrecuencia para reafirmación intensa.",
    },
    {
        "name": "Masaje Corporal 30min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Masaje relajante de 30 minutos que alivia tensiones y mejora la circulación.",
    },
    {
        "name": "Masaje Corporal 60min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Masaje corporal completo de 60 minutos que relaja profundamente y mejora el bienestar.",
    },
    {
        "name": "Peeling Corporal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Exfoliación corporal que elimina células muertas y renueva la piel dejándola suave y luminosa.",
    },
    {
        "name": "Higiene de Espalda",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Limpieza profunda de espalda que elimina impurezas y previene imperfecciones cutáneas.",
    },

    # --- ESTÉTICA FACIAL ---
    {
        "name": "Tinte de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tinte profesional de pestañas para realzar la mirada sin necesidad de maquillaje diario.",
    },
    {
        "name": "Permanente de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Permanente que curva y levanta las pestañas naturalmente para una mirada más abierta.",
    },
    {
        "name": "Tinte + Permanente de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Servicio completo que combina tinte y permanente de pestañas para una mirada impactante.",
    },
    {
        "name": "Maquillaje",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Maquillaje profesional completo para eventos especiales. Realza tu belleza natural.",
    },
    {
        "name": "Maquillaje Express",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Maquillaje rápido y natural para el día a día. Perfecto para eventos informales.",
    },

    # --- DEPILACIÓN ---
    {
        "name": "Depilación Piernas Completas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Depilación completa de piernas enteras con cera para piel suave y duradera.",
    },
    {
        "name": "Depilación Medias Piernas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de medias piernas desde rodilla hasta tobillo.",
    },
    {
        "name": "Depilación Muslos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de muslos completa.",
    },
    {
        "name": "Depilación Ingles",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de zona de ingles. Piel suave y sin irritaciones.",
    },
    {
        "name": "Depilación Ingles Brasileñas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación brasileña que deja la piel suave y sin irritaciones. Técnica profesional.",
    },
    {
        "name": "Depilación Pubis Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación completa de la zona púbica con cera profesional.",
    },
    {
        "name": "Depilación Axilas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de zona de axilas. Piel suave y sin irritaciones.",
    },
    {
        "name": "Depilación Brazos Completos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de brazos completos o zona del pecho según necesidad.",
    },
    {
        "name": "Depilación Pecho Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona del pecho completo.",
    },
    {
        "name": "Depilación Medios Brazos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 20,
        "description": "Depilación con cera de los medios brazos desde el codo hasta la muñeca.",
    },
    {
        "name": "Depilación Abdomen",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona abdominal.",
    },
    {
        "name": "Depilación Glúteos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de glúteos.",
    },
    {
        "name": "Depilación Espalda",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de espalda.",
    },
    {
        "name": "Depilación Labio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 10,
        "description": "Depilación con cera de la zona del labio superior. Tratamiento rápido y efectivo.",
    },
    {
        "name": "Depilación Cejas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 15,
        "description": "Depilación y perfilado de cejas para realzar la mirada y armonizar el rostro.",
    },

    # --- MANICURA Y PEDICURA ---
    {
        "name": "Manicura de Caballero",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Cuidado completo de manos masculinas con limado y acabado natural.",
    },
    {
        "name": "Limar y Pintar Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Arreglo básico de manos con limado de uñas y aplicación de esmalte tradicional.",
    },
    {
        "name": "Limar y Pintar Manos Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Manicura con esmalte permanente de larga duración y acabado profesional.",
    },
    {
        "name": "Bioterapia de Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 45,
        "description": "Tratamiento intensivo para manos que nutre e hidrata la piel en profundidad.",
    },
    {
        "name": "Manicura Permanente + Bioterapia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Manicura permanente completa con tratamiento de bioterapia de manos para nutrición profunda.",
    },
    {
        "name": "Limar y Pintar Pies",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Arreglo básico de pies con limado de uñas y aplicación de esmalte tradicional.",
    },
    {
        "name": "Limar y Pintar Pies Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Pedicura con esmalte permanente de larga duración y acabado impecable.",
    },
    {
        "name": "Bioterapia Podal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento completo de pies con productos naturales que hidratan y regeneran la piel.",
    },
    {
        "name": "Pedicura Permanente + Bioterapia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Pedicura completa con esmalte permanente y tratamiento de bioterapia podal para pies perfectos.",
    },
    {
        "name": "Quita Esmalte Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 25,
        "description": "Retirada profesional de esmalte permanente sin dañar la uña natural.",
    },

    # --- CONSULTA GRATUITA ---
    {
        "name": "Consulta Gratuita Estética",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 10,
        "description": "Consulta estética gratuita de 10 minutos para evaluar tratamientos y necesidades.",
    },
]

# Consolidar todos los servicios
ALL_SERVICES = HAIRDRESSING_SERVICES + AESTHETICS_SERVICES


async def seed_services() -> None:
    """
    Seed services table with ALL services from atrevetepeluqueria.com

    Uses UPSERT logic (check by name before inserting) to avoid duplicates.
    This replaces the old services with the complete catalog from the website.
    """
    async with get_async_session() as session:
        seeded_count = 0
        skipped_count = 0

        for service_data in ALL_SERVICES:
            # Check if service already exists by name
            stmt = select(Service).where(Service.name == service_data["name"])
            result = await session.execute(stmt)
            existing_service = result.scalar_one_or_none()

            if existing_service is None:
                # Create new service
                service = Service(**service_data)
                session.add(service)
                seeded_count += 1
            else:
                skipped_count += 1

        await session.commit()

        # Statistics
        total_services = len(ALL_SERVICES)
        total_hair = len(HAIRDRESSING_SERVICES)
        total_aesthetics = len(AESTHETICS_SERVICES)

        print(f"✓ Seeded {seeded_count} new services (skipped {skipped_count} existing)")
        print(f"  Total services in catalog: {total_services}")
        print(f"  - Peluquería: {total_hair}")
        print(f"  - Estética: {total_aesthetics}")


if __name__ == "__main__":
    asyncio.run(seed_services())
