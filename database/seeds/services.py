"""
Seed data script for services table - VERSIÓN ACTUALIZADA desde PDF oficial

Este archivo contiene los 76 servicios oficiales de Atrévete Peluquería:
- 35 servicios de Peluquería (Corte Dama NO existe en el catálogo real)
- 41 servicios de Estética

Datos actualizados desde el PDF oficial de servicios (2026).
Can be run standalone: python -m database.seeds.services

IMPORTANTE: Los servicios usan UUIDs determinísticos basados en el nombre.
Esto garantiza que el mismo servicio siempre tenga el mismo UUID,
evitar problemas de service_ids huérfanos en citas existentes.

DISAMBIGUATION METADATA (metadata_ field):
All services have structured metadata for service disambiguation.

Metadata shape:
  {
    "family": str,                  # service family key
    "audience": str | None,         # "baby", "child_male", "child_female", "adult_male", "adult_female"
                                    # None means unisex (applies to all audiences)
    "disambiguation_tags": [str],   # keywords that map a customer utterance to this service
    "ask_if_missing": [str],        # clarification dimensions: "audience", "hair_length", "hair_density"
    "variant": str | None,          # "standard" | "extra" | "long"
    "hair_length": str | None,      # "short_medium" | "long"
    "hair_density": str | None,     # "normal" | "extra"
    "combo_recommendations": [str], # suggested add-on service names
  }
"""

import asyncio
import hashlib
from uuid import UUID

from sqlalchemy import select

from database.connection import get_async_session
from database.models import Service, ServiceCategory

# Namespace fijo para generar UUIDs determinísticos
SERVICE_UUID_NAMESPACE = "atrevete-peluqueria-services"


def generate_service_uuid(service_name: str) -> UUID:
    """
    Genera un UUID determinístico basado en el nombre del servicio.

    Esto garantiza que el mismo servicio siempre tenga el mismo UUID,
    independientemente de cuántas veces se ejecute el seed.

    Args:
        service_name: Nombre del servicio

    Returns:
        UUID determinístico y único para ese nombre de servicio
    """
    # Crear hash SHA-256 del namespace + nombre
    combined = f"{SERVICE_UUID_NAMESPACE}:{service_name}"
    hash_bytes = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    # Usar los primeros 32 caracteres del hash como UUID
    return UUID(hash_bytes[:32])


# ============================================================================
# SERVICIOS DE PELUQUERÍA (36 servicios)
# ============================================================================

HAIRDRESSING_SERVICES = [
    {
        "name": "Óleo Pigmento",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Tratamiento regulador de la porosidad capilar que equilibra el pH y mejora la salud del cabello",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["óleo pigmento", "oleo pigmento", "pigmento", "porosidad"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Agua Tierra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 25,
        "description": "Tratamiento capilar detoxificante que purifica el cuero cabelludo y equilibra la grasa",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["agua tierra", "detox capilar", "purificar cuero cabelludo"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Corte de Flequillo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Corte y modelado del flequillo para renovar tu look rápidamente",
        "metadata_": {
            "family": "haircut",
            "audience": None,
            "disambiguation_tags": ["flequillo", "corte flequillo", "fleco"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Perilla",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Arreglo de la perilla (patillas) para un look limpio y pulcro",
        "metadata_": {
            "family": "beard",
            "audience": "adult_male",
            "disambiguation_tags": ["perilla", "patillas", "arreglo patillas"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Barba"],
        },
    },
    {
        "name": "Tratamiento Precolor",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 5,
        "description": "Tratamiento previo al color que prepara el cabello para un mejor resultado",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["tratamiento precolor", "precolor", "preparación color"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Infoactivo Fuerza",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Tratamiento fortalecedor que activa la fuerza capilar desde la raíz",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": [
                "infoactivo fuerza",
                "tratamiento fuerza",
                "fortalecer cabello",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Infoactivo Sensitivo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Tratamiento específico para cabellos sensibles o irritados que calma y protege",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": [
                "infoactivo sensitivo",
                "tratamiento sensitivo",
                "cabello sensible",
                "cuero cabelludo sensible",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Mechas Localizadas",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 20,
        "description": "Mechas en zonas específicas para aportar luz y dimensión al cabello",
        "metadata_": {
            "family": "highlights",
            "audience": None,
            "disambiguation_tags": ["mechas localizadas", "mechas puntuales", "toque de luz"],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": "normal",
            "combo_recommendations": ["Peinado"],
        },
    },
    {
        "name": "Color Caballero",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Servicio de coloración específico para cabellos masculinos",
        "metadata_": {
            "family": "color",
            "audience": "adult_male",
            "disambiguation_tags": [
                "color caballero",
                "tinte hombre",
                "coloración hombre",
                "color hombre",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Cultura de Color",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Servicio de coloración profesional con productos de alta calidad",
        "metadata_": {
            "family": "color",
            "audience": None,
            "disambiguation_tags": ["cultura de color", "color", "coloración", "tinte"],
            "ask_if_missing": ["hair_density"],
            "variant": "standard",
            "hair_length": None,
            "hair_density": "normal",
            "combo_recommendations": ["Peinado", "Óleo Pigmento"],
        },
    },
    {
        "name": "Recogido",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Peinado recogido elegante para eventos y ocasiones especiales",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": ["recogido", "peinado recogido", "updo"],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Semirecogido",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Peinado semirecogido que combina elegancia con un toque natural",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": ["semirecogido", "semi recogido", "medio recogido"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Recogido Novia",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Peinado de novia completo con prueba y ejecución el día de la boda",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": ["recogido novia", "peinado novia", "boda recogido", "novia"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Maquillaje Novia"],
        },
    },
    {
        "name": "Corte Bebé",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 20,
        "description": "Corte capilar suave y rápido para los más pequeños de la casa",
        "metadata_": {
            "family": "haircut",
            "audience": "baby",
            "disambiguation_tags": [
                "bebé",
                "bebe",
                "bebito",
                "bebita",
                "muy pequeño",
                "muy pequeña",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Peinado", "Barro", "Óleo Pigmento"],
        },
    },
    {
        "name": "Mechas",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Servicio completo de mechas para iluminar y dar dimensión al cabello",
        "metadata_": {
            "family": "highlights",
            "audience": None,
            "disambiguation_tags": ["mechas", "highlights", "reflejos", "luces", "balayage"],
            "ask_if_missing": ["hair_density"],
            "variant": "standard",
            "hair_length": None,
            "hair_density": "normal",
            "combo_recommendations": ["Peinado", "Barro"],
        },
    },
    {
        "name": "Mechas Extras",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Servicio de mechas extendido para cabellos largos o con mucha densidad",
        "metadata_": {
            "family": "highlights",
            "audience": None,
            "disambiguation_tags": [
                "mechas extras",
                "mechas extra",
                "mechas largo",
                "mechas larga",
                "mucho pelo",
            ],
            "ask_if_missing": [],
            "variant": "extra",
            "hair_length": None,
            "hair_density": "extra",
            "combo_recommendations": ["Peinado Largo", "Barro"],
        },
    },
    {
        "name": "Barro Gold",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento de coloración con barro que nutre mientras aporta tonos dorados",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["barro gold", "barro dorado", "tratamiento barro gold"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Mechas Localizadas Express",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Versión express de mechas localizadas para un toque de luz rápido",
        "metadata_": {
            "family": "highlights",
            "audience": None,
            "disambiguation_tags": [
                "mechas localizadas express",
                "mechas express",
                "mechas rápidas",
            ],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": "normal",
            "combo_recommendations": [],
        },
    },
    {
        "name": "Óleo Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento intensivo con óleos esenciales para cabello muy dañado o seco",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["óleo extra", "oleo extra", "tratamiento óleo extra"],
            "ask_if_missing": [],
            "variant": "extra",
            "hair_length": None,
            "hair_density": "extra",
            "combo_recommendations": [],
        },
    },
    {
        "name": "Barro Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento de barro intensivo para cabellos que necesitan nutrición profunda",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["barro extra", "tratamiento barro extra"],
            "ask_if_missing": [],
            "variant": "extra",
            "hair_length": None,
            "hair_density": "extra",
            "combo_recommendations": [],
        },
    },
    {
        "name": "Barba",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Arreglo y modelado de barba para un look cuidado y masculino",
        "metadata_": {
            "family": "beard",
            "audience": "adult_male",
            "disambiguation_tags": ["barba", "arreglo barba", "modelado barba"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Corte Caballero"],
        },
    },
    {
        "name": "Moldeado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Moldeado extendido para cabellos largos o con tratamientos químicos previos",
        "metadata_": {
            "family": "perm",
            "audience": None,
            "disambiguation_tags": ["moldeado extra", "moldeado largo", "moldeado mucho pelo"],
            "ask_if_missing": [],
            "variant": "extra",
            "hair_length": None,
            "hair_density": "extra",
            "combo_recommendations": ["Peinado Largo", "Barro"],
        },
    },
    {
        "name": "Agua Lluvia",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 25,
        "description": "Tratamiento hidratante que aporta brillo y suavidad como la lluvia fresca",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["agua lluvia", "tratamiento agua lluvia", "hidratante brillo"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Cultura de Color Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 50,
        "description": "Servicio de coloración extendido para cambios drásticos o correcciones",
        "metadata_": {
            "family": "color",
            "audience": None,
            "disambiguation_tags": [
                "cultura de color extra",
                "color extra",
                "coloración extra",
                "cambio drástico",
            ],
            "ask_if_missing": [],
            "variant": "extra",
            "hair_length": None,
            "hair_density": "extra",
            "combo_recommendations": [],
        },
    },
    {
        "name": "Prepigmentar",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Proceso de prepigmentación para preparar el cabello antes de ciertos colores",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["prepigmentar", "prepigmentación", "preparación pigmento"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Cortar",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Corte capilar completo con lavado incluido",
        "metadata_": {
            "family": "haircut",
            "audience": "adult_female",
            "disambiguation_tags": [
                "cortar",
                "corte",
                "corte adulto",
                "corte mujer",
                "corte señora",
                "corte dama",
                "mujer adulta",
                "señora",
                "dama",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Peinado", "Barro"],
        },
    },
    {
        "name": "Peinado Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 45,
        "description": "Peinado profesional para cabello largo, incluye lavado ritual facial",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": ["peinado largo", "peinado cabello largo", "blow dry largo"],
            "ask_if_missing": [],
            "variant": "long",
            "hair_length": "long",
            "hair_density": None,
            "combo_recommendations": ["Barro", "Óleo Pigmento"],
        },
    },
    {
        "name": "Barro",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento de coloración con barro natural que nutre el cabello",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["barro", "tratamiento barro", "barro natural"],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": "normal",
            "combo_recommendations": [],
        },
    },
    {
        "name": "Peinado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Peinado extendido para cabello muy largo o elaborado",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": [
                "peinado extra",
                "peinado muy largo",
                "peinado elaborado",
                "peinado mucho pelo",
            ],
            "ask_if_missing": [],
            "variant": "extra",
            "hair_length": "long",
            "hair_density": "extra",
            "combo_recommendations": ["Barro", "Óleo Pigmento"],
        },
    },
    {
        "name": "Corte Niña",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Corte especializado para niñas con técnicas adaptadas a su edad",
        "metadata_": {
            "family": "haircut",
            "audience": "child_female",
            "disambiguation_tags": ["corte niña", "niña", "chica", "nena"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Peinado"],
        },
    },
    {
        "name": "Peinado Niña Comunión",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Peinado elegante para niñas en su Primera Comunión",
        "metadata_": {
            "family": "hairstyle",
            "audience": "child_female",
            "disambiguation_tags": [
                "peinado niña comunión",
                "comunión",
                "primera comunión",
                "peinado comunión",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Secado",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 20,
        "description": "Secado profesional del cabello para un acabado pulcro",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": ["secado", "secado cabello", "blow dry"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Peinado",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Peinado profesional para el día a día o eventos informales",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": ["peinado", "blow dry", "secado con forma", "marcado"],
            "ask_if_missing": ["hair_length"],
            "variant": "standard",
            "hair_length": "short_medium",
            "hair_density": None,
            "combo_recommendations": ["Barro", "Óleo Pigmento"],
        },
    },
    {
        "name": "Corte Niño",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Corte especializado para niños con técnicas adaptadas a su edad",
        "metadata_": {
            "family": "haircut",
            "audience": "child_male",
            "disambiguation_tags": ["corte niño", "niño", "chico", "nene"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Peinado"],
        },
    },
    {
        "name": "Corte Caballero",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Corte capilar completo para caballeros con lavado incluido",
        "metadata_": {
            "family": "haircut",
            "audience": "adult_male",
            "disambiguation_tags": ["corte caballero", "caballero", "hombre", "señor", "varón"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Barba"],
        },
    },
]


# ============================================================================
# SERVICIOS DE ESTÉTICA (41 servicios)
# ============================================================================

AESTHETICS_SERVICES = [
    {
        "name": "Masaje Corporal (60 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Masaje corporal relajante de cuerpo completo para aliviar tensiones y estrés acumulado",
        "metadata_": {
            "family": "massage",
            "audience": None,
            "disambiguation_tags": [
                "masaje corporal",
                "masaje 60 minutos",
                "masaje relajante",
                "masaje completo",
            ],
            "ask_if_missing": [],
            "variant": "long",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Maquillaje",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Servicio de maquillaje profesional para eventos, fiestas y ocasiones especiales",
        "metadata_": {
            "family": "makeup",
            "audience": None,
            "disambiguation_tags": [
                "maquillaje",
                "makeup",
                "maquillaje evento",
                "maquillaje fiesta",
            ],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Tinte de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento para dar color oscuro y duradero a las pestañas naturales",
        "metadata_": {
            "family": "lashes",
            "audience": None,
            "disambiguation_tags": ["tinte pestañas", "tinte de pestañas", "color pestañas"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Peeling Corporal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Exfoliación corporal profunda que renueva la piel eliminando células muertas",
        "metadata_": {
            "family": "body_treatment",
            "audience": None,
            "disambiguation_tags": ["peeling corporal", "exfoliación corporal", "exfoliar cuerpo"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Tinte + Permanente de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento combinado que da color y curvatura natural duradera a las pestañas",
        "metadata_": {
            "family": "lashes",
            "audience": None,
            "disambiguation_tags": [
                "tinte y permanente pestañas",
                "tinte permanente pestañas",
                "color y curvatura pestañas",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Permanente de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento para dar curvatura natural y duradera a las pestañas sin necesidad de rizador",
        "metadata_": {
            "family": "lashes",
            "audience": None,
            "disambiguation_tags": [
                "permanente pestañas",
                "curvatura pestañas",
                "rizar pestañas",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bioterapia Facial + Radiofrecuencia (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento facial avanzado combinado con 30 minutos de radiofrecuencia para resultados anti-edad potenciados",
        "metadata_": {
            "family": "facial",
            "audience": None,
            "disambiguation_tags": [
                "bioterapia facial radiofrecuencia 30",
                "facial radiofrecuencia 30 minutos",
                "anti-edad facial",
            ],
            "ask_if_missing": [],
            "variant": "long",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bioterapia Facial + Radiofrecuencia (15 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Tratamiento facial combinado con 15 minutos de radiofrecuencia para rejuvenecimiento facial",
        "metadata_": {
            "family": "facial",
            "audience": None,
            "disambiguation_tags": [
                "bioterapia facial radiofrecuencia 15",
                "facial radiofrecuencia 15 minutos",
                "rejuvenecimiento facial",
            ],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bioterapia Facial",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento facial personalizado según las necesidades específicas de tu piel",
        "metadata_": {
            "family": "facial",
            "audience": None,
            "disambiguation_tags": [
                "bioterapia facial",
                "facial",
                "limpieza facial",
                "tratamiento facial",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Maquillaje Express",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Maquillaje rápido y profesional para el día a día o eventos informales",
        "metadata_": {
            "family": "makeup",
            "audience": None,
            "disambiguation_tags": ["maquillaje express", "maquillaje rápido", "maquillaje diario"],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Brazos Completos o Pecho",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de brazos completos o zona del pecho",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "brazos completos",
                "depilación brazos",
                "cera brazos",
                "depilación pecho",
                "cera pecho",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Higiene de Espalda",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Limpieza facial especializada para la espalda, ideal para tratar impurezas y acné",
        "metadata_": {
            "family": "facial",
            "audience": None,
            "disambiguation_tags": [
                "higiene espalda",
                "limpieza espalda",
                "acné espalda",
                "impurezas espalda",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Maquillaje Novia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 70,
        "description": "Maquillaje profesional para novias con prueba previa y duración todo el evento",
        "metadata_": {
            "family": "makeup",
            "audience": None,
            "disambiguation_tags": [
                "maquillaje novia",
                "makeup novia",
                "maquillaje boda",
                "novia maquillaje",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Recogido Novia"],
        },
    },
    {
        "name": "Cejas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 15,
        "description": "Depilación con cera y diseño de cejas para enmarcar la mirada",
        "metadata_": {
            "family": "brows",
            "audience": None,
            "disambiguation_tags": ["cejas", "depilación cejas", "diseño cejas", "arreglo cejas"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Ingles o Axilas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de ingles o axilas",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "ingles",
                "axilas",
                "depilación ingles",
                "depilación axilas",
                "cera ingles",
                "cera axilas",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Manicura Permanente + Bio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Manicura con esmalte permanente combinado con tratamiento bioterapéutico para manos",
        "metadata_": {
            "family": "nails",
            "audience": None,
            "disambiguation_tags": [
                "manicura permanente bio",
                "manicura permanente bioterapia",
                "esmaltado permanente bio",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bioterapia Sculptor + Radiofrecuencia 30 min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento corporal anticelulítico combinado con 30 minutos de radiofrecuencia para resultados potenciados",
        "metadata_": {
            "family": "body_treatment",
            "audience": None,
            "disambiguation_tags": [
                "bioterapia sculptor radiofrecuencia",
                "anticelulítico radiofrecuencia",
                "sculptor radiofrecuencia 30",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Limar y Pintar Manos Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Servicio de limado y esmaltado permanente de uñas de manos",
        "metadata_": {
            "family": "nails",
            "audience": None,
            "disambiguation_tags": [
                "limar pintar manos permanente",
                "esmaltado permanente manos",
                "uñas permanente manos",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Brazos Medios",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de media brazo (antebrazo o parte superior)",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "brazos medios",
                "media brazo",
                "depilación media brazo",
                "cera media brazo",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bioterapia de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento que aumenta naturalmente el volumen del seno mejorando hidratación y tonicidad",
        "metadata_": {
            "family": "body_treatment",
            "audience": None,
            "disambiguation_tags": [
                "bioterapia senos",
                "tratamiento senos",
                "volumen senos",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Bono Bioterapia de Senos"],
        },
    },
    {
        "name": "Masaje Corporal (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Masaje corporal relajante de 30 minutos para aliviar tensiones específicas",
        "metadata_": {
            "family": "massage",
            "audience": None,
            "disambiguation_tags": [
                "masaje corporal 30 minutos",
                "masaje 30 min",
                "masaje relajante corto",
            ],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bono Bioterapia de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Bono de sesiones de bioterapia de senos con precio especial",
        "metadata_": {
            "family": "body_treatment",
            "audience": None,
            "disambiguation_tags": [
                "bono bioterapia senos",
                "bono senos",
                "pack bioterapia senos",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Quita Esmalte Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 25,
        "description": "Servicio de retirada de esmalte permanente de uñas",
        "metadata_": {
            "family": "nails",
            "audience": None,
            "disambiguation_tags": [
                "quitar esmalte permanente",
                "quita esmalte",
                "retirada esmalte permanente",
                "quitar uñas permanente",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Medios Brazos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 20,
        "description": "Depilación con cera de media brazo (antebrazo o parte superior)",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "medios brazos",
                "depilación medios brazos",
                "cera medios brazos",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Piernas Perfectas + Presoterapia (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Tratamiento combinado que drena toxinas, descongestiona y reafirma las piernas",
        "metadata_": {
            "family": "body_treatment",
            "audience": None,
            "disambiguation_tags": [
                "piernas perfectas presoterapia",
                "presoterapia piernas",
                "drenaje piernas",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Cera Enteras",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Depilación con cera de piernas enteras",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "cera piernas enteras",
                "depilación piernas completas",
                "cera piernas completas",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Cera Medias Piernas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de medias piernas",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "cera medias piernas",
                "depilación media pierna",
                "cera media pierna",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Abdomen, Glúteos, Espalda o Pecho",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de una zona a elegir: abdomen, glúteos, espalda o pecho",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "abdomen",
                "glúteos",
                "espalda",
                "cera abdomen",
                "cera glúteos",
                "cera espalda",
                "depilación abdomen",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Cera Muslos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de los muslos",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": ["cera muslos", "depilación muslos", "muslos cera"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Pubis Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona del pubis completo",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "pubis completo",
                "depilación pubis",
                "cera pubis",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Ingles Brasileñas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de ingles al estilo brasileño",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "ingles brasileñas",
                "brasileño",
                "depilación brasileña",
                "cera brasileña",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Barro Gold Extra",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento facial con barro dorado de alta gama para nutrición profunda",
        "metadata_": {
            "family": "facial",
            "audience": None,
            "disambiguation_tags": [
                "barro gold extra",
                "barro dorado extra",
                "tratamiento facial barro gold",
            ],
            "ask_if_missing": [],
            "variant": "extra",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bioterapia Sculptor Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento corporal anticelulítico completo que reduce nódulos grasos y retención de líquidos",
        "metadata_": {
            "family": "body_treatment",
            "audience": None,
            "disambiguation_tags": [
                "bioterapia sculptor completo",
                "anticelulítico completo",
                "sculptor completo",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bioterapia Podal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento específico para pies cansados y fatigados que hidrata y revitaliza",
        "metadata_": {
            "family": "body_treatment",
            "audience": None,
            "disambiguation_tags": [
                "bioterapia podal",
                "tratamiento pies",
                "pies cansados",
                "revitalizar pies",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Limar y Pintar Pies",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Servicio básico de limado y esmaltado de uñas de pies",
        "metadata_": {
            "family": "nails",
            "audience": None,
            "disambiguation_tags": [
                "limar pintar pies",
                "esmaltado pies",
                "uñas pies",
                "pintar pies",
            ],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Limar y Pintar Pies Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Servicio de limado y esmaltado permanente de uñas de pies",
        "metadata_": {
            "family": "nails",
            "audience": None,
            "disambiguation_tags": [
                "limar pintar pies permanente",
                "esmaltado permanente pies",
                "uñas permanente pies",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Bioterapia de Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 45,
        "description": "Tratamiento específico para hidratar, rejuvenecer y cuidar las manos",
        "metadata_": {
            "family": "body_treatment",
            "audience": None,
            "disambiguation_tags": [
                "bioterapia manos",
                "tratamiento manos",
                "hidratación manos",
                "rejuvenecer manos",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Pedicura Permanente con Bioterapia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Pedicura completa con esmalte permanente y tratamiento bioterapéutico para pies",
        "metadata_": {
            "family": "nails",
            "audience": None,
            "disambiguation_tags": [
                "pedicura permanente bioterapia",
                "pedicura permanente",
                "pedicura con bioterapia",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Manicura Caballero",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Manicura profesional para caballeros con limado, cutículas e hidratación",
        "metadata_": {
            "family": "nails",
            "audience": "adult_male",
            "disambiguation_tags": [
                "manicura caballero",
                "manicura hombre",
                "uñas caballero",
                "uñas hombre",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Limar y Pintar Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Servicio básico de limado y esmaltado de uñas de manos",
        "metadata_": {
            "family": "nails",
            "audience": None,
            "disambiguation_tags": [
                "limar pintar manos",
                "esmaltado manos",
                "uñas manos",
                "pintar manos",
            ],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
    {
        "name": "Labio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 10,
        "description": "Depilación con cera del labio superior o inferior",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": [
                "labio",
                "depilación labio",
                "cera labio",
                "bigote",
                "labio superior",
            ],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": [],
        },
    },
]


# Consolidar todos los servicios
ALL_SERVICES = HAIRDRESSING_SERVICES + AESTHETICS_SERVICES


async def seed_services() -> None:
    """
    Seed services table with the official services (77 hairdressing + aesthetics).

    Usa UPSERT para preservar UUIDs existentes y evitar romper referencias en citas.
    Los UUIDs son determinísticos basados en el nombre del servicio.

    IMPORTANTE: Este script NO elimina servicios existentes. Para la limpieza completa
    (eliminar servicios no presentes en el PDF), usar el script de migración correspondiente.
    """
    async with get_async_session() as session:
        created_count = 0
        updated_count = 0

        for service_data in ALL_SERVICES:
            # Generar UUID determinístico basado en nombre
            service_uuid = generate_service_uuid(service_data["name"])

            # Buscar servicio existente por UUID determinístico
            existing = await session.execute(select(Service).where(Service.id == service_uuid))
            service = existing.scalar_one_or_none()

            if service:
                # Actualizar servicio existente
                service.category = service_data["category"]
                service.duration_minutes = service_data["duration_minutes"]
                service.description = service_data.get("description")
                service.metadata_ = service_data.get("metadata_", {})
                service.is_active = True
                updated_count += 1
            else:
                # Crear nuevo servicio con UUID determinístico
                new_service = Service(
                    id=service_uuid,
                    name=service_data["name"],
                    category=service_data["category"],
                    duration_minutes=service_data["duration_minutes"],
                    description=service_data.get("description"),
                    metadata_=service_data.get("metadata_", {}),
                    is_active=True,
                )
                session.add(new_service)
                created_count += 1

        await session.commit()

        # Statistics
        total_services = len(ALL_SERVICES)
        total_hair = len(HAIRDRESSING_SERVICES)
        total_aesthetics = len(AESTHETICS_SERVICES)

        print("✓ Services seed completed:")
        print(f"  - Created: {created_count} new services")
        print(f"  - Updated: {updated_count} existing services")
        print(f"  - Total: {total_services} services")
        print(f"  - Peluquería: {total_hair}")
        print(f"  - Estética: {total_aesthetics}")


if __name__ == "__main__":
    asyncio.run(seed_services())
