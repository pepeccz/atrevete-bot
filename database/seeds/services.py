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

AUDIENCE FIELD (top-level):
Each service has an audience= top-level field for filtering by customer profile.
Valid values: "adult_female", "adult_male", "child_female", "child_male", "unisex", None
None means the service applies to all audiences.

METADATA FIELD (data-driven disambiguation):
Each service carries metadata_ with 3 keys:
- service_type: "principal" | "variant" | "addon"
    * principal → default when customer speaks generically ("cortarme el pelo", "uñas")
    * variant   → punctual alternative of a principal (the customer asks for it explicitly)
    * addon     → complementary / auxiliary service (treatments, pre-color steps, nail removal)
- dimension: stable key grouping services by purpose
    * hairdressing: cut | color | highlights | hairstyle | updo | blowdry | treatment
    * aesthetics:   manicure | pedicure | facial | massage | makeup | wax | eyelash
                    | hand_treatment | foot_treatment | body_contour | body_treatment
- parent_service_name: name of the principal this variant belongs to (exact match).
  None for principals and most addons.

The catalog_builder.py consumes these fields to emit [PRINCIPAL · dim · audience],
[VARIANTE de X], and [ADDON · dim] tags visible to the LLM.
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
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "treatment", "parent_service_name": None},
    },
    {
        "name": "Agua Tierra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 25,
        "description": "Detox capilar: purifica el cuero cabelludo y reduce el exceso de grasa (25 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "treatment", "parent_service_name": None},
    },
    {
        "name": "Corte de Flequillo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Recorte y modelado del flequillo. Sin lavado ni secado, ideal para un retoque rápido (15 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "cut", "parent_service_name": "Cortar"},
    },
    {
        "name": "Perilla",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Perfilado de patillas con navaja. Acabado preciso para un look prolijo (10 min)",
        "audience": "adult_male",
        "metadata_": {"service_type": "variant", "dimension": "cut", "parent_service_name": "Corte Caballero"},
    },
    {
        "name": "Tratamiento Precolor",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 5,
        "description": "Preparación del cabello antes de la coloración para potenciar el resultado (5 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "color", "parent_service_name": None},
    },
    {
        "name": "Infoactivo Fuerza",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Tratamiento que refuerza la fibra capilar desde la raíz. Para cabello debilitado (30 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "treatment", "parent_service_name": None},
    },
    {
        "name": "Infoactivo Sensitivo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Calma el cuero cabelludo sensible o irritado y lo protege (30 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "treatment", "parent_service_name": None},
    },
    {
        "name": "Mechas Localizadas",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 20,
        "description": "Mechas solo en zonas elegidas: sin full-head. Ideal para un toque de luz puntual (20 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "highlights", "parent_service_name": "Mechas"},
    },
    {
        "name": "Color Caballero",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Coloración específica para cabellos masculinos. Cubre canas con resultado natural (30 min)",
        "audience": "adult_male",
        "metadata_": {"service_type": "principal", "dimension": "color", "parent_service_name": None},
    },
    {
        "name": "Cultura de Color",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Coloración completa con lavado, aplicación y resultado uniforme. Cabello normal (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "color", "parent_service_name": None},
    },
    {
        "name": "Recogido",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Peinado recogido para eventos especiales. Incluye diseño y fijación profesional (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "updo", "parent_service_name": None},
    },
    {
        "name": "Semirecogido",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Recogido parcial para looks elegantes sin estructuras rígidas (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "updo", "parent_service_name": "Recogido"},
    },
    {
        "name": "Recogido Novia",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Recogido completo de novia: prueba previa y ejecución el día del evento (120 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "updo", "parent_service_name": "Recogido"},
    },
    {
        "name": "Corte Bebé",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 20,
        "description": "Primer corte para bebés con técnica suave y paciencia extra. Rápido y sin tensiones (20 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "cut", "parent_service_name": None},
    },
    {
        "name": "Mechas",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 60,
        "description": "Mechas completas con lavado y procesado. Para cabello normal (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "highlights", "parent_service_name": None},
    },
    {
        "name": "Mechas Extras",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Mechas completas para cabello con más volumen o largo extra. 10 min más que Mechas estándar (70 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "highlights", "parent_service_name": "Mechas"},
    },
    {
        "name": "Barro Gold",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento con barro que aporta tonos dorados cálidos mientras nutre (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "treatment", "parent_service_name": "Barro"},
    },
    {
        "name": "Mechas Localizadas Express",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Versión express de Mechas Localizadas. Resultado rápido en zonas puntuales (15 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "highlights", "parent_service_name": "Mechas"},
    },
    {
        "name": "Óleo Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento intensivo con óleos para cabello muy seco o químicamente dañado (40 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "treatment", "parent_service_name": None},
    },
    {
        "name": "Barro Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Barro intensivo para cabello con alta densidad o daño avanzado (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "treatment", "parent_service_name": "Barro"},
    },
    {
        "name": "Barba",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 15,
        "description": "Arreglo, perfilado y modelado de barba para un acabado limpio y definido (15 min)",
        "audience": "adult_male",
        "metadata_": {"service_type": "variant", "dimension": "cut", "parent_service_name": "Corte Caballero"},
    },
    {
        "name": "Moldeado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Moldeado para cabello largo o muy denso. Más tiempo de proceso que el estándar (70 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "hairstyle", "parent_service_name": "Peinado"},
    },
    {
        "name": "Agua Lluvia",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 25,
        "description": "Hidratación intensa que aporta suavidad y brillo sin pesar el cabello (25 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "treatment", "parent_service_name": None},
    },
    {
        "name": "Cultura de Color Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 50,
        "description": "Coloración extendida para cabello muy denso o cambios de tono importantes (50 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "color", "parent_service_name": "Cultura de Color"},
    },
    {
        "name": "Prepigmentar",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Prepigmentación: permite aplicar colores oscuros sobre cabello muy aclarado (10 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "color", "parent_service_name": None},
    },
    {
        "name": "Cortar",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Corte para dama con lavado, corte y secado incluidos. Longitud estándar (40 min)",
        "audience": "adult_female",
        "metadata_": {"service_type": "principal", "dimension": "cut", "parent_service_name": None},
    },
    {
        "name": "Peinado Largo",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 45,
        "description": "Lavado + secado con forma para cabello largo. Más tiempo de trabajo (45 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "hairstyle", "parent_service_name": "Peinado"},
    },
    {
        "name": "Barro",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Tratamiento nutritivo con barro natural: cierra la cutícula y da brillo duradero (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "treatment", "parent_service_name": None},
    },
    {
        "name": "Peinado Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Lavado + secado para cabello muy largo o con mucho volumen. Versión más extensa (70 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "hairstyle", "parent_service_name": "Peinado"},
    },
    {
        "name": "Corte Niña",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Corte con lavado y secado para niñas. Técnicas adaptadas a su edad y tipo de cabello (30 min)",
        "audience": "child_female",
        "metadata_": {"service_type": "principal", "dimension": "cut", "parent_service_name": None},
    },
    {
        "name": "Peinado Niña Comunión",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 70,
        "description": "Peinado de gala para niñas en su Primera Comunión. Diseño elegante y duradero (70 min)",
        "audience": "child_female",
        "metadata_": {"service_type": "variant", "dimension": "hairstyle", "parent_service_name": "Peinado"},
    },
    {
        "name": "Secado",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 20,
        "description": "Secado profesional sin lavado. Para quienes ya vienen con el pelo mojado (20 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "blowdry", "parent_service_name": None},
    },
    {
        "name": "Peinado",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Lavado + secado con forma para cabello corto/medio. El estilo del día a día (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "hairstyle", "parent_service_name": None},
    },
    {
        "name": "Corte Niño",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Corte con lavado y secado para niños. Estilo y comodidad pensados para los más activos (30 min)",
        "audience": "child_male",
        "metadata_": {"service_type": "principal", "dimension": "cut", "parent_service_name": None},
    },
    {
        "name": "Corte Caballero",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Corte con lavado y secado para caballeros. Incluye modelado y acabado profesional (40 min)",
        "audience": "adult_male",
        "metadata_": {"service_type": "principal", "dimension": "cut", "parent_service_name": None},
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
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "massage", "parent_service_name": None},
    },
    {
        "name": "Maquillaje",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Maquillaje profesional para eventos y fiestas. Adaptado a tu estilo y ocasión (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "makeup", "parent_service_name": None},
    },
    {
        "name": "Tinte de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Da color oscuro y duradero a las pestañas naturales. Sin extensiones (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "eyelash", "parent_service_name": None},
    },
    {
        "name": "Peeling Corporal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Exfoliación corporal profunda. Elimina células muertas y renueva la textura de la piel (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "body_treatment", "parent_service_name": None},
    },
    {
        "name": "Tinte + Permanente de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Combina color + curvatura duradera en un solo turno. Más completo (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "eyelash", "parent_service_name": "Tinte de Pestañas"},
    },
    {
        "name": "Permanente de Pestañas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Curvatura duradera para las pestañas sin rizador. Resultado natural (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "eyelash", "parent_service_name": None},
    },
    {
        "name": "Bioterapia Facial + Radiofrecuencia (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Facial + 30 min de radiofrecuencia. Máxima potencia anti-edad (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "facial", "parent_service_name": "Bioterapia Facial"},
    },
    {
        "name": "Bioterapia Facial + Radiofrecuencia (15 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Facial + 15 min de radiofrecuencia para reafirmar y rejuvenecer la piel (75 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "facial", "parent_service_name": "Bioterapia Facial"},
    },
    {
        "name": "Bioterapia Facial",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento facial personalizado según el tipo de piel. Limpieza, nutrición y equilibrio (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "facial", "parent_service_name": None},
    },
    {
        "name": "Maquillaje Express",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Maquillaje rápido y prolijo para el día a día. Resultado fresco en 30 min",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "makeup", "parent_service_name": "Maquillaje"},
    },
    {
        "name": "Brazos Completos o Pecho",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de brazos completos o zona del pecho a elegir (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Higiene de Espalda",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Limpieza profunda de la espalda para tratar poros, impurezas y granos (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "body_treatment", "parent_service_name": None},
    },
    {
        "name": "Maquillaje Novia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 70,
        "description": "Maquillaje de novia con prueba previa. Duración garantizada durante todo el evento (70 min)",
        "audience": "adult_female",
        "metadata_": {"service_type": "variant", "dimension": "makeup", "parent_service_name": "Maquillaje"},
    },
    {
        "name": "Cejas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 15,
        "description": "Diseño y depilación con cera. Da forma y limpia el contorno para enmarcar la mirada (15 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Ingles o Axilas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de ingles o axilas a elección. Piel lisa y sin irritación (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Manicura Permanente + Bio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Esmaltado permanente + tratamiento bioterapéutico para manos en un solo turno (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "manicure", "parent_service_name": "Limar y Pintar Manos"},
    },
    {
        "name": "Bioterapia Sculptor + Radiofrecuencia 30 min",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Sculptor + 30 min de radiofrecuencia para resultados anticelulíticos potenciados (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "body_contour", "parent_service_name": "Bioterapia Sculptor Completo"},
    },
    {
        "name": "Limar y Pintar Manos Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Esmaltado permanente de manos con durabilidad de hasta 3 semanas (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "manicure", "parent_service_name": "Limar y Pintar Manos"},
    },
    {
        "name": "Brazos Medios",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de media brazo: antebrazo o parte superior a elegir (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Bioterapia de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento natural que mejora tonicidad e hidratación de la zona del busto (60 min)",
        "audience": "adult_female",
        "metadata_": {"service_type": "principal", "dimension": "body_treatment", "parent_service_name": None},
    },
    {
        "name": "Masaje Corporal (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Masaje relajante de 30 min para aliviar tensiones y descansar zonas específicas",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "massage", "parent_service_name": "Masaje Corporal (60 min)"},
    },
    {
        "name": "Bono Bioterapia de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Pack de sesiones de Bioterapia de Senos para un resultado más progresivo y duradero (60 min)",
        "audience": "adult_female",
        "metadata_": {"service_type": "variant", "dimension": "body_treatment", "parent_service_name": "Bioterapia de Senos"},
    },
    {
        "name": "Quita Esmalte Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 25,
        "description": "Retirada segura del esmalte permanente sin dañar la uña natural (25 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "manicure", "parent_service_name": None},
    },
    {
        "name": "Medios Brazos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 20,
        "description": "Depilación con cera de media brazo. Variante más rápida sin incluir codo (20 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Piernas Perfectas + Presoterapia (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Drenaje + descongestión + reafirmación de piernas. Combinado con presoterapia (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "body_contour", "parent_service_name": "Bioterapia Sculptor Completo"},
    },
    {
        "name": "Cera Enteras",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Depilación con cera de piernas enteras: desde tobillo hasta ingle (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "wax", "parent_service_name": None},
    },
    {
        "name": "Cera Medias Piernas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de media pierna: pantorrilla o muslo a elegir (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Abdomen, Glúteos, Espalda o Pecho",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de una zona a elegir. Resultado limpio y prolijo (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Cera Muslos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de los muslos. Completa la media pierna (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Pubis Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona del pubis al completo (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Ingles Brasileñas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera al estilo brasileño: elimina todo el vello de la zona íntima (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
    {
        "name": "Barro Gold Extra",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento facial con barro dorado extra para nutrición profunda y luminosidad (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "facial", "parent_service_name": "Bioterapia Facial"},
    },
    {
        "name": "Bioterapia Sculptor Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento anticelulítico completo: reduce nódulos y retención de líquidos (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "body_contour", "parent_service_name": None},
    },
    {
        "name": "Bioterapia Podal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento específico para pies: hidrata, revitaliza y alivia la fatiga (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "foot_treatment", "parent_service_name": None},
    },
    {
        "name": "Limar y Pintar Pies",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Limado + esmaltado estándar de uñas de pies (30 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "pedicure", "parent_service_name": None},
    },
    {
        "name": "Limar y Pintar Pies Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Esmaltado permanente de pies. Duración y color que aguanta todo (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "pedicure", "parent_service_name": "Limar y Pintar Pies"},
    },
    {
        "name": "Bioterapia de Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 45,
        "description": "Hidratación y revitalización intensiva de manos. Piel suave y rejuvenecida (45 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "hand_treatment", "parent_service_name": None},
    },
    {
        "name": "Pedicura Permanente con Bioterapia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Pedicura completa + esmaltado permanente + bioterapia para pies en un turno (75 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "pedicure", "parent_service_name": "Limar y Pintar Pies"},
    },
    {
        "name": "Manicura Caballero",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Manicura profesional para caballeros: limado, cutículas e hidratación (30 min)",
        "audience": "adult_male",
        "metadata_": {"service_type": "variant", "dimension": "manicure", "parent_service_name": "Limar y Pintar Manos"},
    },
    {
        "name": "Limar y Pintar Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Limado + esmaltado estándar de uñas de manos. Sin tratamiento adicional (30 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "manicure", "parent_service_name": None},
    },
    {
        "name": "Labio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 10,
        "description": "Depilación con cera del labio superior. Resultado suave y duradero (10 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Cera Enteras"},
    },
]


# Consolidar todos los servicios
ALL_SERVICES = HAIRDRESSING_SERVICES + AESTHETICS_SERVICES


# ============================================================================
# DIMENSIONS REFERENCE
# ============================================================================
#
# Stable dimension keys used in metadata_["dimension"]. When adding a new
# service, re-use an existing dimension if at all possible. Introduce a new
# dimension only when the service is genuinely not a variant of anything.
#
# HAIRDRESSING:
#   - cut         → Cortar / Corte Caballero / Corte Niño / Corte Niña / Corte Bebé
#                   (variants: Corte de Flequillo, Perilla, Barba)
#   - color       → Cultura de Color / Color Caballero
#                   (variants: Cultura de Color Extra; addons: Tratamiento Precolor, Prepigmentar)
#   - highlights  → Mechas
#                   (variants: Mechas Extras, Mechas Localizadas, Mechas Localizadas Express)
#   - hairstyle   → Peinado
#                   (variants: Peinado Largo, Peinado Extra, Moldeado Extra, Peinado Niña Comunión)
#   - updo        → Recogido
#                   (variants: Semirecogido, Recogido Novia)
#   - blowdry     → Secado
#   - treatment   → Barro
#                   (variants: Barro Gold, Barro Extra;
#                    addons: Óleo Pigmento, Agua Tierra, Agua Lluvia, Óleo Extra,
#                            Infoactivo Fuerza, Infoactivo Sensitivo)
#
# AESTHETICS:
#   - manicure        → Limar y Pintar Manos
#                       (variants: Limar y Pintar Manos Permanente, Manicura Permanente + Bio,
#                                  Manicura Caballero; addons: Quita Esmalte Permanente)
#   - pedicure        → Limar y Pintar Pies
#                       (variants: Limar y Pintar Pies Permanente, Pedicura Permanente con Bioterapia)
#   - facial          → Bioterapia Facial
#                       (variants: Bioterapia Facial + Radiofrecuencia 15/30 min, Barro Gold Extra)
#   - massage         → Masaje Corporal (60 min)
#                       (variants: Masaje Corporal (30 min))
#   - makeup          → Maquillaje
#                       (variants: Maquillaje Express, Maquillaje Novia)
#   - wax             → Cera Enteras
#                       (variants: everything else under "depilación con cera")
#   - eyelash         → Tinte de Pestañas / Permanente de Pestañas
#                       (variants: Tinte + Permanente de Pestañas)
#   - hand_treatment  → Bioterapia de Manos
#   - foot_treatment  → Bioterapia Podal
#   - body_contour    → Bioterapia Sculptor Completo
#                       (variants: Bioterapia Sculptor + Radiofrecuencia,
#                                  Piernas Perfectas + Presoterapia)
#   - body_treatment  → Peeling Corporal / Higiene de Espalda / Bioterapia de Senos
#                       (variants: Bono Bioterapia de Senos)


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
                service.audience = service_data.get("audience")
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
                    audience=service_data.get("audience"),
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
