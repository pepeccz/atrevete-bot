"""
Seed data script for services table - VERSIÓN ACTUALIZADA desde PDF oficial

Este archivo contiene los 76 servicios oficiales de Atrévete Peluquería:
- 35 servicios de Peluquería
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
        "metadata_": {"service_type": "variant", "dimension": "cut", "parent_service_name": "Corte de Mujer"},
    },
    {
        "name": "Perilla",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 10,
        "description": "Perfilado de patillas con navaja. Acabado preciso para un look prolijo (10 min)",
        "audience": "adult_male",
        "metadata_": {"service_type": "variant", "dimension": "cut", "parent_service_name": "Corte de Hombre"},
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
        "name": "Color para Hombre",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Cultura de Color específica para caballeros. Cubre canas con resultado natural (30 min)",
        "audience": "adult_male",
        "metadata_": {"service_type": "principal", "dimension": "color", "parent_service_name": None},
    },
    {
        "name": "Tinte",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Cultura de Color: coloración completa con lavado, aplicación y resultado uniforme. Cabello normal (40 min)",
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
        "name": "Recogido de Novia",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 120,
        "description": "Recogido completo de novia: prueba previa y ejecución el día del evento (120 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "updo", "parent_service_name": "Recogido"},
    },
    {
        "name": "Corte de Bebé",
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
        "name": "Mechas Localizadas Exprés",
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
        "metadata_": {"service_type": "variant", "dimension": "cut", "parent_service_name": "Corte de Hombre"},
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
        "name": "Tinte Extra",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 50,
        "description": "Cultura de Color extendida para cabello muy denso o cambios de tono importantes (50 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "color", "parent_service_name": "Tinte"},
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
        "name": "Corte de Mujer",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Corte de dama con lavado, corte y secado incluidos. Longitud estándar (40 min)",
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
        "name": "Corte de Niña",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Corte con lavado y secado para niñas. Técnicas adaptadas a su edad y tipo de cabello (30 min)",
        "audience": "child_female",
        "metadata_": {"service_type": "principal", "dimension": "cut", "parent_service_name": None},
    },
    {
        "name": "Peinado de Comunión",
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
        "name": "Corte de Niño",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 30,
        "description": "Corte con lavado y secado para niños. Estilo y comodidad pensados para los más activos (30 min)",
        "audience": "child_male",
        "metadata_": {"service_type": "principal", "dimension": "cut", "parent_service_name": None},
    },
    {
        "name": "Corte de Hombre",
        "category": ServiceCategory.HAIRDRESSING,
        "duration_minutes": 40,
        "description": "Corte de caballero con lavado y secado. Incluye modelado y acabado profesional (40 min)",
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
        "name": "Exfoliación Corporal",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Peeling corporal: exfoliación profunda que elimina células muertas y renueva la textura de la piel (60 min)",
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
        "name": "Tratamiento Facial + Radiofrecuencia (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Facial + 30 min de radiofrecuencia. Máxima potencia anti-edad (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "facial", "parent_service_name": "Tratamiento Facial"},
    },
    {
        "name": "Tratamiento Facial + Radiofrecuencia (15 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Facial + 15 min de radiofrecuencia para reafirmar y rejuvenecer la piel (75 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "facial", "parent_service_name": "Tratamiento Facial"},
    },
    {
        "name": "Tratamiento Facial",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Bioterapia facial personalizada según el tipo de piel: limpieza, nutrición y equilibrio (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "facial", "parent_service_name": None},
    },
    {
        "name": "Maquillaje Exprés",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Maquillaje rápido y prolijo para el día a día. Resultado fresco en 30 min",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "makeup", "parent_service_name": "Maquillaje"},
    },
    {
        "name": "Depilación de Brazos Enteros o Pecho",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de brazos completos o zona del pecho a elegir (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Limpieza de Espalda",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Higiene profunda de la espalda: extracción de impurezas, granos y limpieza de poros (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "body_treatment", "parent_service_name": None},
    },
    {
        "name": "Maquillaje de Novia",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 70,
        "description": "Maquillaje de novia con prueba previa. Duración garantizada durante todo el evento (70 min)",
        "audience": "adult_female",
        "metadata_": {"service_type": "variant", "dimension": "makeup", "parent_service_name": "Maquillaje"},
    },
    {
        "name": "Depilación de Cejas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 15,
        "description": "Diseño y depilación con cera. Da forma y limpia el contorno para enmarcar la mirada (15 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Depilación de Ingles o Axilas",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de ingles o axilas a elección. Piel lisa y sin irritación (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Manicura Permanente con Tratamiento",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Limar uñas + esmaltado semipermanente + tratamiento hidratante de manos en un solo turno (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "manicure", "parent_service_name": "Manicura"},
    },
    {
        "name": "Tratamiento Anticelulítico + Radiofrecuencia (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Sculptor + 30 min de radiofrecuencia para resultados anticelulíticos potenciados (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "body_contour", "parent_service_name": "Tratamiento Anticelulítico Completo"},
    },
    {
        "name": "Manicura Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Limar uñas + esmaltado semipermanente de manos. Durabilidad de hasta 3 semanas (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "manicure", "parent_service_name": "Manicura"},
    },
    {
        "name": "Depilación de Antebrazo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de medio brazo: antebrazo o parte superior a elegir (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Tratamiento de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Bioterapia de senos: tratamiento natural que mejora tonicidad e hidratación de la zona del busto (60 min)",
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
        "name": "Bono Tratamiento de Senos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Pack de sesiones del tratamiento bioterapéutico de senos para un resultado más progresivo y duradero (60 min)",
        "audience": "adult_female",
        "metadata_": {"service_type": "variant", "dimension": "body_treatment", "parent_service_name": "Tratamiento de Senos"},
    },
    {
        "name": "Retirada de Esmalte Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 25,
        "description": "Quitar esmalte semipermanente de uñas de forma segura, sin dañar la uña natural (25 min)",
        "audience": None,
        "metadata_": {"service_type": "addon", "dimension": "manicure", "parent_service_name": None},
    },
    {
        "name": "Depilación de Medio Brazo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 20,
        "description": "Depilación con cera de media brazo. Variante más rápida sin incluir codo (20 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Piernas Perfectas + Presoterapia (30 min)",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 90,
        "description": "Drenaje + descongestión + reafirmación de piernas. Combinado con presoterapia (90 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "body_contour", "parent_service_name": "Tratamiento Anticelulítico Completo"},
    },
    {
        "name": "Depilación de Piernas Enteras",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Depilación con cera de piernas enteras: desde tobillo hasta ingle, ambas piernas completas (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "wax", "parent_service_name": None},
    },
    {
        "name": "Depilación de Media Pierna",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de media pierna: pantorrilla o muslo a elegir (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Depilación de Abdomen, Glúteos, Espalda o Pecho",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de una zona a elegir. Resultado limpio y prolijo (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Depilación de Muslos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona de los muslos. Completa la media pierna (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Depilación de Pubis Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de la zona del pubis al completo (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Depilación Brasileña",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Depilación con cera de ingles brasileñas: elimina todo el vello de la zona íntima (30 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
    },
    {
        "name": "Barro Gold Extra",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento facial con barro dorado extra para nutrición profunda y luminosidad (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "facial", "parent_service_name": "Tratamiento Facial"},
    },
    {
        "name": "Tratamiento Anticelulítico Completo",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 60,
        "description": "Tratamiento Sculptor anticelulítico completo: reduce nódulos, drena y combate la retención de líquidos (60 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "body_contour", "parent_service_name": None},
    },
    {
        "name": "Tratamiento de Pies",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Tratamiento bioterapéutico podal: hidrata, revitaliza y alivia la fatiga. No incluye esmaltado (40 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "foot_treatment", "parent_service_name": None},
    },
    {
        "name": "Pedicura",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Limar uñas + esmaltado tradicional de pies. Dura aproximadamente 1 semana (30 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "pedicure", "parent_service_name": None},
    },
    {
        "name": "Pedicura Permanente",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 40,
        "description": "Limar uñas + esmaltado semipermanente de pies. Durabilidad de hasta 3 semanas (40 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "pedicure", "parent_service_name": "Pedicura"},
    },
    {
        "name": "Tratamiento de Manos",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 45,
        "description": "Tratamiento bioterapéutico de manos: hidratación y revitalización intensiva. No incluye esmaltado (45 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "hand_treatment", "parent_service_name": None},
    },
    {
        "name": "Pedicura Permanente con Tratamiento",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 75,
        "description": "Pedicura completa + esmaltado semipermanente + tratamiento hidratante de pies en un turno (75 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "pedicure", "parent_service_name": "Pedicura"},
    },
    {
        "name": "Manicura de Hombre",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Manicura específica para caballeros: limado, arreglo de cutículas e hidratación. Sin esmalte (30 min)",
        "audience": "adult_male",
        "metadata_": {"service_type": "variant", "dimension": "manicure", "parent_service_name": "Manicura"},
    },
    {
        "name": "Manicura",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 30,
        "description": "Limar uñas + esmaltado tradicional de manos. Dura aproximadamente 1 semana (30 min)",
        "audience": None,
        "metadata_": {"service_type": "principal", "dimension": "manicure", "parent_service_name": None},
    },
    {
        "name": "Depilación de Labio",
        "category": ServiceCategory.AESTHETICS,
        "duration_minutes": 10,
        "description": "Depilación con cera del labio superior. Resultado suave y duradero (10 min)",
        "audience": None,
        "metadata_": {"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación de Piernas Enteras"},
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
#   - cut         → Corte de Mujer / Corte de Hombre / Corte de Niño / Corte de Niña / Corte de Bebé
#                   (variants: Corte de Flequillo, Perilla, Barba)
#   - color       → Tinte / Color para Hombre
#                   (variants: Tinte Extra; addons: Tratamiento Precolor, Prepigmentar)
#   - highlights  → Mechas
#                   (variants: Mechas Extras, Mechas Localizadas, Mechas Localizadas Exprés)
#   - hairstyle   → Peinado
#                   (variants: Peinado Largo, Peinado Extra, Moldeado Extra, Peinado de Comunión)
#   - updo        → Recogido
#                   (variants: Semirecogido, Recogido de Novia)
#   - blowdry     → Secado
#   - treatment   → Barro
#                   (variants: Barro Gold, Barro Extra;
#                    addons: Óleo Pigmento, Agua Tierra, Agua Lluvia, Óleo Extra,
#                            Infoactivo Fuerza, Infoactivo Sensitivo)
#
# AESTHETICS:
#   - manicure        → Manicura
#                       (variants: Manicura Permanente, Manicura Permanente con Tratamiento,
#                                  Manicura de Hombre; addons: Retirada de Esmalte Permanente)
#   - pedicure        → Pedicura
#                       (variants: Pedicura Permanente, Pedicura Permanente con Tratamiento)
#   - facial          → Tratamiento Facial
#                       (variants: Tratamiento Facial + Radiofrecuencia 15/30 min, Barro Gold Extra)
#   - massage         → Masaje Corporal (60 min)
#                       (variants: Masaje Corporal (30 min))
#   - makeup          → Maquillaje
#                       (variants: Maquillaje Exprés, Maquillaje de Novia)
#   - wax             → Depilación de Piernas Enteras
#                       (variants: everything else under "depilación con cera")
#   - eyelash         → Tinte de Pestañas / Permanente de Pestañas
#                       (variants: Tinte + Permanente de Pestañas)
#   - hand_treatment  → Tratamiento de Manos
#   - foot_treatment  → Tratamiento de Pies
#   - body_contour    → Tratamiento Anticelulítico Completo
#                       (variants: Tratamiento Anticelulítico + Radiofrecuencia,
#                                  Piernas Perfectas + Presoterapia)
#   - body_treatment  → Exfoliación Corporal / Limpieza de Espalda / Tratamiento de Senos
#                       (variants: Bono Tratamiento de Senos)


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
