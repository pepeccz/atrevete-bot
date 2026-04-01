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
        "description": "Regula la porosidad y equilibra el pH. Deja el cabello brillante y manejable (30 min)",
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
        "description": "Detox capilar: purifica el cuero cabelludo y reduce el exceso de grasa (25 min)",
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
        "description": "Recorte y modelado del flequillo. Sin lavado ni secado, ideal para un retoque rápido (15 min)",
        "metadata_": {
            "family": "haircut",
            "audience": None,
            "disambiguation_tags": ["flequillo", "corte flequillo", "fleco"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Peinado"],
        },
    },
    {
        "name": "Perilla",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Perfilado de patillas con navaja. Acabado preciso para un look prolijo (10 min)",
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
        "description": "Preparación del cabello antes de la coloración para potenciar el resultado (5 min)",
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
        "description": "Tratamiento que refuerza la fibra capilar desde la raíz. Para cabello debilitado (30 min)",
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
        "description": "Calma el cuero cabelludo sensible o irritado y lo protege (30 min)",
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
        "description": "Mechas solo en zonas elegidas: sin full-head. Ideal para un toque de luz puntual (20 min)",
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
        "description": "Coloración específica para cabellos masculinos. Cubre canas con resultado natural (30 min)",
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
            "combo_recommendations": ["Barba"],
        },
    },
    {
        "name": "Cultura de Color",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Coloración completa con lavado, aplicación y resultado uniforme. Cabello normal (40 min)",
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
        "description": "Peinado recogido para eventos especiales. Incluye diseño y fijación profesional (60 min)",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": ["recogido", "peinado recogido", "updo"],
            "ask_if_missing": [],
            "variant": "standard",
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Secado"],
        },
    },
    {
        "name": "Semirecogido",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Recogido parcial para looks elegantes sin estructuras rígidas (40 min)",
        "metadata_": {
            "family": "hairstyle",
            "audience": None,
            "disambiguation_tags": ["semirecogido", "semi recogido", "medio recogido"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Secado"],
        },
    },
    {
        "name": "Recogido Novia",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Recogido completo de novia: prueba previa y ejecución el día del evento (120 min)",
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
        "description": "Primer corte para bebés con técnica suave y paciencia extra. Rápido y sin tensiones (20 min)",
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
        "description": "Mechas completas con lavado y procesado. Para cabello normal (60 min)",
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
        "description": "Mechas completas para cabello con más volumen o largo extra. 10 min más que Mechas estándar (70 min)",
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
        "description": "Tratamiento con barro que aporta tonos dorados cálidos mientras nutre (40 min)",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["barro gold", "barro dorado", "tratamiento barro gold"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Peinado", "Óleo Pigmento"],
        },
    },
    {
        "name": "Mechas Localizadas Express",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Versión express de Mechas Localizadas. Resultado rápido en zonas puntuales (15 min)",
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
            "combo_recommendations": ["Peinado"],
        },
    },
    {
        "name": "Óleo Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento intensivo con óleos para cabello muy seco o químicamente dañado (40 min)",
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
        "description": "Barro intensivo para cabello con alta densidad o daño avanzado (40 min)",
        "metadata_": {
            "family": "treatment",
            "audience": None,
            "disambiguation_tags": ["barro extra", "tratamiento barro extra"],
            "ask_if_missing": [],
            "variant": "extra",
            "hair_length": None,
            "hair_density": "extra",
            "combo_recommendations": ["Peinado Largo"],
        },
    },
    {
        "name": "Barba",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Arreglo, perfilado y modelado de barba para un acabado limpio y definido (15 min)",
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
        "description": "Moldeado para cabello largo o muy denso. Más tiempo de proceso que el estándar (70 min)",
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
        "description": "Hidratación intensa que aporta suavidad y brillo sin pesar el cabello (25 min)",
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
        "description": "Coloración extendida para cabello muy denso o cambios de tono importantes (50 min)",
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
            "combo_recommendations": ["Peinado", "Óleo Pigmento"],
        },
    },
    {
        "name": "Prepigmentar",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Prepigmentación: permite aplicar colores oscuros sobre cabello muy aclarado (10 min)",
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
        "description": "Corte para dama con lavado, corte y secado incluidos. Longitud estándar (40 min)",
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
        "description": "Lavado + secado con forma para cabello largo. Más tiempo de trabajo (45 min)",
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
        "description": "Tratamiento nutritivo con barro natural: cierra la cutícula y da brillo duradero (40 min)",
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
        "description": "Lavado + secado para cabello muy largo o con mucho volumen. Versión más extensa (70 min)",
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
        "description": "Corte con lavado y secado para niñas. Técnicas adaptadas a su edad y tipo de cabello (30 min)",
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
        "description": "Peinado de gala para niñas en su Primera Comunión. Diseño elegante y duradero (70 min)",
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
        "description": "Secado profesional sin lavado. Para quienes ya vienen con el pelo mojado (20 min)",
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
        "description": "Lavado + secado con forma para cabello corto/medio. El estilo del día a día (40 min)",
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
        "description": "Corte con lavado y secado para niños. Estilo y comodidad pensados para los más activos (30 min)",
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
        "description": "Corte con lavado y secado para caballeros. Incluye modelado y acabado profesional (40 min)",
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
        "description": "Masaje de cuerpo completo de 60 min. Profunda relajación y alivio muscular (60 min)",
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
            "combo_recommendations": ["Peeling Corporal"],
        },
    },
    {
        "name": "Maquillaje",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Maquillaje profesional para eventos y fiestas. Adaptado a tu estilo y ocasión (60 min)",
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
        "description": "Da color oscuro y duradero a las pestañas naturales. Sin extensiones (40 min)",
        "metadata_": {
            "family": "lashes",
            "audience": None,
            "disambiguation_tags": ["tinte pestañas", "tinte de pestañas", "color pestañas"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Permanente de Pestañas"],
        },
    },
    {
        "name": "Peeling Corporal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Exfoliación corporal profunda. Elimina células muertas y renueva la textura de la piel (60 min)",
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
        "description": "Combina color + curvatura duradera en un solo turno. Más completo (90 min)",
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
        "description": "Curvatura duradera para las pestañas sin rizador. Resultado natural (40 min)",
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
            "combo_recommendations": ["Tinte de Pestañas"],
        },
    },
    {
        "name": "Bioterapia Facial + Radiofrecuencia (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Facial + 30 min de radiofrecuencia. Máxima potencia anti-edad (90 min)",
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
        "description": "Facial + 15 min de radiofrecuencia para reafirmar y rejuvenecer la piel (75 min)",
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
        "description": "Tratamiento facial personalizado según el tipo de piel. Limpieza, nutrición y equilibrio (60 min)",
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
            "combo_recommendations": ["Bioterapia Facial + Radiofrecuencia (15 min)"],
        },
    },
    {
        "name": "Maquillaje Express",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Maquillaje rápido y prolijo para el día a día. Resultado fresco en 30 min",
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
        "description": "Depilación con cera de brazos completos o zona del pecho a elegir (30 min)",
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
        "description": "Limpieza profunda de la espalda para tratar poros, impurezas y granos (60 min)",
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
        "description": "Maquillaje de novia con prueba previa. Duración garantizada durante todo el evento (70 min)",
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
        "description": "Diseño y depilación con cera. Da forma y limpia el contorno para enmarcar la mirada (15 min)",
        "metadata_": {
            "family": "brows",
            "audience": None,
            "disambiguation_tags": ["cejas", "depilación cejas", "diseño cejas", "arreglo cejas"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Labio"],
        },
    },
    {
        "name": "Ingles o Axilas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de ingles o axilas a elección. Piel lisa y sin irritación (30 min)",
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
            "combo_recommendations": ["Cera Medias Piernas"],
        },
    },
    {
        "name": "Manicura Permanente + Bio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Esmaltado permanente + tratamiento bioterapéutico para manos en un solo turno (90 min)",
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
            "combo_recommendations": ["Pedicura Permanente con Bioterapia"],
        },
    },
    {
        "name": "Bioterapia Sculptor + Radiofrecuencia 30 min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Sculptor + 30 min de radiofrecuencia para resultados anticelulíticos potenciados (90 min)",
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
        "description": "Esmaltado permanente de manos con durabilidad de hasta 3 semanas (40 min)",
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
        "description": "Depilación con cera de media brazo: antebrazo o parte superior a elegir (30 min)",
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
        "description": "Tratamiento natural que mejora tonicidad e hidratación de la zona del busto (60 min)",
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
        "description": "Masaje relajante de 30 min para aliviar tensiones y descansar zonas específicas",
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
            "combo_recommendations": ["Masaje Corporal (60 min)", "Peeling Corporal"],
        },
    },
    {
        "name": "Bono Bioterapia de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Pack de sesiones de Bioterapia de Senos para un resultado más progresivo y duradero (60 min)",
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
        "description": "Retirada segura del esmalte permanente sin dañar la uña natural (25 min)",
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
        "description": "Depilación con cera de media brazo. Variante más rápida sin incluir codo (20 min)",
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
        "description": "Drenaje + descongestión + reafirmación de piernas. Combinado con presoterapia (90 min)",
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
        "description": "Depilación con cera de piernas enteras: desde tobillo hasta ingle (40 min)",
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
            "combo_recommendations": ["Ingles o Axilas"],
        },
    },
    {
        "name": "Cera Medias Piernas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de media pierna: pantorrilla o muslo a elegir (30 min)",
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
            "combo_recommendations": ["Cera Muslos"],
        },
    },
    {
        "name": "Abdomen, Glúteos, Espalda o Pecho",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de una zona a elegir. Resultado limpio y prolijo (30 min)",
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
        "description": "Depilación con cera de la zona de los muslos. Completa la media pierna (30 min)",
        "metadata_": {
            "family": "waxing",
            "audience": None,
            "disambiguation_tags": ["cera muslos", "depilación muslos", "muslos cera"],
            "ask_if_missing": [],
            "variant": None,
            "hair_length": None,
            "hair_density": None,
            "combo_recommendations": ["Cera Medias Piernas"],
        },
    },
    {
        "name": "Pubis Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona del pubis al completo (30 min)",
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
        "description": "Depilación con cera al estilo brasileño: elimina todo el vello de la zona íntima (30 min)",
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
        "description": "Tratamiento facial con barro dorado extra para nutrición profunda y luminosidad (40 min)",
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
        "description": "Tratamiento anticelulítico completo: reduce nódulos y retención de líquidos (60 min)",
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
        "description": "Tratamiento específico para pies: hidrata, revitaliza y alivia la fatiga (40 min)",
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
            "combo_recommendations": ["Limar y Pintar Pies", "Limar y Pintar Pies Permanente"],
        },
    },
    {
        "name": "Limar y Pintar Pies",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Limado + esmaltado estándar de uñas de pies (30 min)",
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
            "combo_recommendations": ["Limar y Pintar Pies Permanente"],
        },
    },
    {
        "name": "Limar y Pintar Pies Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Esmaltado permanente de pies. Duración y color que aguanta todo (40 min)",
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
        "description": "Hidratación y revitalización intensiva de manos. Piel suave y rejuvenecida (45 min)",
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
            "combo_recommendations": ["Limar y Pintar Manos", "Manicura Permanente + Bio"],
        },
    },
    {
        "name": "Pedicura Permanente con Bioterapia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Pedicura completa + esmaltado permanente + bioterapia para pies en un turno (75 min)",
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
        "description": "Manicura profesional para caballeros: limado, cutículas e hidratación (30 min)",
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
        "description": "Limado + esmaltado estándar de uñas de manos. Sin tratamiento adicional (30 min)",
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
            "combo_recommendations": ["Limar y Pintar Manos Permanente"],
        },
    },
    {
        "name": "Labio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 10,
        "description": "Depilación con cera del labio superior. Resultado suave y duradero (10 min)",
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
