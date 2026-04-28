"""Rename services to natural names + add Service.price_cents column.

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-04-27

Changes:
1. Add `price_cents` (Integer, nullable) column to `services` (EUR cents).
2. UPDATE service rows in-place (matched by deterministic UUID derived from
   the OLD name) renaming `name` to a more natural Spanish version and
   improving `description` to preserve the original scope so the WhatsApp
   agent can explain what each service includes.

IMPORTANT: This migration only UPDATEs existing rows; it does NOT regenerate
UUIDs nor INSERT new rows. Existing appointment.service_id references
remain valid.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from database.seeds.services import generate_service_uuid

# revision identifiers, used by Alembic.
revision: str = "y5z6a7b8c9d0"
down_revision: Union[str, None] = "x4y5z6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (old_name, new_name, new_description)
RENAMES: list[tuple[str, str, str]] = [
    # Hairdressing
    (
        "Color Caballero",
        "Color para Hombre",
        "Cultura de Color específica para caballeros. Cubre canas con resultado natural (30 min)",
    ),
    (
        "Cultura de Color",
        "Tinte",
        "Cultura de Color: coloración completa con lavado, aplicación y resultado uniforme. Cabello normal (40 min)",
    ),
    (
        "Recogido Novia",
        "Recogido de Novia",
        "Recogido completo de novia: prueba previa y ejecución el día del evento (120 min)",
    ),
    (
        "Corte Bebé",
        "Corte de Bebé",
        "Primer corte para bebés con técnica suave y paciencia extra. Rápido y sin tensiones (20 min)",
    ),
    (
        "Mechas Localizadas Express",
        "Mechas Localizadas Exprés",
        "Versión express de Mechas Localizadas. Resultado rápido en zonas puntuales (15 min)",
    ),
    (
        "Cultura de Color Extra",
        "Tinte Extra",
        "Cultura de Color extendida para cabello muy denso o cambios de tono importantes (50 min)",
    ),
    (
        "Corte Dama",
        "Corte de Mujer",
        "Corte de dama con lavado, corte y secado incluidos. Longitud estándar (40 min)",
    ),
    (
        "Corte Niña",
        "Corte de Niña",
        "Corte con lavado y secado para niñas. Técnicas adaptadas a su edad y tipo de cabello (30 min)",
    ),
    (
        "Peinado Niña Comunión",
        "Peinado de Comunión",
        "Peinado de gala para niñas en su Primera Comunión. Diseño elegante y duradero (70 min)",
    ),
    (
        "Corte Niño",
        "Corte de Niño",
        "Corte con lavado y secado para niños. Estilo y comodidad pensados para los más activos (30 min)",
    ),
    (
        "Corte Caballero",
        "Corte de Hombre",
        "Corte de caballero con lavado y secado. Incluye modelado y acabado profesional (40 min)",
    ),
    # Aesthetics
    (
        "Peeling Corporal",
        "Exfoliación Corporal",
        "Peeling corporal: exfoliación profunda que elimina células muertas y renueva la textura de la piel (60 min)",
    ),
    (
        "Bioterapia Facial + Radiofrecuencia (30 min)",
        "Tratamiento Facial + Radiofrecuencia (30 min)",
        "Facial + 30 min de radiofrecuencia. Máxima potencia anti-edad (90 min)",
    ),
    (
        "Bioterapia Facial + Radiofrecuencia (15 min)",
        "Tratamiento Facial + Radiofrecuencia (15 min)",
        "Facial + 15 min de radiofrecuencia para reafirmar y rejuvenecer la piel (75 min)",
    ),
    (
        "Bioterapia Facial",
        "Tratamiento Facial",
        "Bioterapia facial personalizada según el tipo de piel: limpieza, nutrición y equilibrio (60 min)",
    ),
    (
        "Maquillaje Express",
        "Maquillaje Exprés",
        "Maquillaje rápido y prolijo para el día a día. Resultado fresco en 30 min",
    ),
    (
        "Brazos Completos o Pecho",
        "Depilación de Brazos Enteros o Pecho",
        "Depilación con cera de brazos completos o zona del pecho a elegir (30 min)",
    ),
    (
        "Higiene de Espalda",
        "Limpieza de Espalda",
        "Higiene profunda de la espalda: extracción de impurezas, granos y limpieza de poros (60 min)",
    ),
    (
        "Maquillaje Novia",
        "Maquillaje de Novia",
        "Maquillaje de novia con prueba previa. Duración garantizada durante todo el evento (70 min)",
    ),
    (
        "Cejas",
        "Depilación de Cejas",
        "Diseño y depilación con cera. Da forma y limpia el contorno para enmarcar la mirada (15 min)",
    ),
    (
        "Ingles o Axilas",
        "Depilación de Ingles o Axilas",
        "Depilación con cera de ingles o axilas a elección. Piel lisa y sin irritación (30 min)",
    ),
    (
        "Manicura Permanente + Bio",
        "Manicura Permanente con Tratamiento",
        "Limar uñas + esmaltado semipermanente + tratamiento hidratante de manos en un solo turno (90 min)",
    ),
    (
        "Bioterapia Sculptor + Radiofrecuencia 30 min",
        "Tratamiento Anticelulítico + Radiofrecuencia (30 min)",
        "Sculptor + 30 min de radiofrecuencia para resultados anticelulíticos potenciados (90 min)",
    ),
    (
        "Limar y Pintar Manos Permanente",
        "Manicura Permanente",
        "Limar uñas + esmaltado semipermanente de manos. Durabilidad de hasta 3 semanas (40 min)",
    ),
    (
        "Brazos Medios",
        "Depilación de Antebrazo",
        "Depilación con cera de medio brazo: antebrazo o parte superior a elegir (30 min)",
    ),
    (
        "Bioterapia de Senos",
        "Tratamiento de Senos",
        "Bioterapia de senos: tratamiento natural que mejora tonicidad e hidratación de la zona del busto (60 min)",
    ),
    (
        "Bono Bioterapia de Senos",
        "Bono Tratamiento de Senos",
        "Pack de sesiones del tratamiento bioterapéutico de senos para un resultado más progresivo y duradero (60 min)",
    ),
    (
        "Quita Esmalte Permanente",
        "Retirada de Esmalte Permanente",
        "Quitar esmalte semipermanente de uñas de forma segura, sin dañar la uña natural (25 min)",
    ),
    (
        "Medios Brazos",
        "Depilación de Medio Brazo",
        "Depilación con cera de media brazo. Variante más rápida sin incluir codo (20 min)",
    ),
    (
        "Cera Enteras",
        "Depilación de Piernas Enteras",
        "Depilación con cera de piernas enteras: desde tobillo hasta ingle, ambas piernas completas (40 min)",
    ),
    (
        "Cera Medias Piernas",
        "Depilación de Media Pierna",
        "Depilación con cera de media pierna: pantorrilla o muslo a elegir (30 min)",
    ),
    (
        "Abdomen, Glúteos, Espalda o Pecho",
        "Depilación de Abdomen, Glúteos, Espalda o Pecho",
        "Depilación con cera de una zona a elegir. Resultado limpio y prolijo (30 min)",
    ),
    (
        "Cera Muslos",
        "Depilación de Muslos",
        "Depilación con cera de la zona de los muslos. Completa la media pierna (30 min)",
    ),
    (
        "Pubis Completo",
        "Depilación de Pubis Completo",
        "Depilación con cera de la zona del pubis al completo (30 min)",
    ),
    (
        "Ingles Brasileñas",
        "Depilación Brasileña",
        "Depilación con cera de ingles brasileñas: elimina todo el vello de la zona íntima (30 min)",
    ),
    (
        "Bioterapia Sculptor Completo",
        "Tratamiento Anticelulítico Completo",
        "Tratamiento Sculptor anticelulítico completo: reduce nódulos, drena y combate la retención de líquidos (60 min)",
    ),
    (
        "Bioterapia Podal",
        "Tratamiento de Pies",
        "Tratamiento bioterapéutico podal: hidrata, revitaliza y alivia la fatiga. No incluye esmaltado (40 min)",
    ),
    (
        "Limar y Pintar Pies",
        "Pedicura",
        "Limar uñas + esmaltado tradicional de pies. Dura aproximadamente 1 semana (30 min)",
    ),
    (
        "Limar y Pintar Pies Permanente",
        "Pedicura Permanente",
        "Limar uñas + esmaltado semipermanente de pies. Durabilidad de hasta 3 semanas (40 min)",
    ),
    (
        "Bioterapia de Manos",
        "Tratamiento de Manos",
        "Tratamiento bioterapéutico de manos: hidratación y revitalización intensiva. No incluye esmaltado (45 min)",
    ),
    (
        "Pedicura Permanente con Bioterapia",
        "Pedicura Permanente con Tratamiento",
        "Pedicura completa + esmaltado semipermanente + tratamiento hidratante de pies en un turno (75 min)",
    ),
    (
        "Manicura Caballero",
        "Manicura de Hombre",
        "Manicura específica para caballeros: limado, arreglo de cutículas e hidratación. Sin esmalte (30 min)",
    ),
    (
        "Limar y Pintar Manos",
        "Manicura",
        "Limar uñas + esmaltado tradicional de manos. Dura aproximadamente 1 semana (30 min)",
    ),
    (
        "Labio",
        "Depilación de Labio",
        "Depilación con cera del labio superior. Resultado suave y duradero (10 min)",
    ),
]


# Old descriptions, indexed by old name — used only by downgrade().
OLD_DESCRIPTIONS: dict[str, str] = {
    "Color Caballero": "Coloración específica para cabellos masculinos. Cubre canas con resultado natural (30 min)",
    "Cultura de Color": "Coloración completa con lavado, aplicación y resultado uniforme. Cabello normal (40 min)",
    "Recogido Novia": "Recogido completo de novia: prueba previa y ejecución el día del evento (120 min)",
    "Corte Bebé": "Primer corte para bebés con técnica suave y paciencia extra. Rápido y sin tensiones (20 min)",
    "Mechas Localizadas Express": "Versión express de Mechas Localizadas. Resultado rápido en zonas puntuales (15 min)",
    "Cultura de Color Extra": "Coloración extendida para cabello muy denso o cambios de tono importantes (50 min)",
    "Corte Dama": "Corte para dama con lavado, corte y secado incluidos. Longitud estándar (40 min)",
    "Corte Niña": "Corte con lavado y secado para niñas. Técnicas adaptadas a su edad y tipo de cabello (30 min)",
    "Peinado Niña Comunión": "Peinado de gala para niñas en su Primera Comunión. Diseño elegante y duradero (70 min)",
    "Corte Niño": "Corte con lavado y secado para niños. Estilo y comodidad pensados para los más activos (30 min)",
    "Corte Caballero": "Corte con lavado y secado para caballeros. Incluye modelado y acabado profesional (40 min)",
    "Peeling Corporal": "Exfoliación corporal profunda. Elimina células muertas y renueva la textura de la piel (60 min)",
    "Bioterapia Facial + Radiofrecuencia (30 min)": "Facial + 30 min de radiofrecuencia. Máxima potencia anti-edad (90 min)",
    "Bioterapia Facial + Radiofrecuencia (15 min)": "Facial + 15 min de radiofrecuencia para reafirmar y rejuvenecer la piel (75 min)",
    "Bioterapia Facial": "Tratamiento facial personalizado según el tipo de piel. Limpieza, nutrición y equilibrio (60 min)",
    "Maquillaje Express": "Maquillaje rápido y prolijo para el día a día. Resultado fresco en 30 min",
    "Brazos Completos o Pecho": "Depilación con cera de brazos completos o zona del pecho a elegir (30 min)",
    "Higiene de Espalda": "Limpieza profunda de la espalda para tratar poros, impurezas y granos (60 min)",
    "Maquillaje Novia": "Maquillaje de novia con prueba previa. Duración garantizada durante todo el evento (70 min)",
    "Cejas": "Diseño y depilación con cera. Da forma y limpia el contorno para enmarcar la mirada (15 min)",
    "Ingles o Axilas": "Depilación con cera de ingles o axilas a elección. Piel lisa y sin irritación (30 min)",
    "Manicura Permanente + Bio": "Esmaltado permanente + tratamiento bioterapéutico para manos en un solo turno (90 min)",
    "Bioterapia Sculptor + Radiofrecuencia 30 min": "Sculptor + 30 min de radiofrecuencia para resultados anticelulíticos potenciados (90 min)",
    "Limar y Pintar Manos Permanente": "Esmaltado permanente de manos con durabilidad de hasta 3 semanas (40 min)",
    "Brazos Medios": "Depilación con cera de media brazo: antebrazo o parte superior a elegir (30 min)",
    "Bioterapia de Senos": "Tratamiento natural que mejora tonicidad e hidratación de la zona del busto (60 min)",
    "Bono Bioterapia de Senos": "Pack de sesiones de Bioterapia de Senos para un resultado más progresivo y duradero (60 min)",
    "Quita Esmalte Permanente": "Retirada segura del esmalte permanente sin dañar la uña natural (25 min)",
    "Medios Brazos": "Depilación con cera de media brazo. Variante más rápida sin incluir codo (20 min)",
    "Cera Enteras": "Depilación con cera de piernas enteras: desde tobillo hasta ingle (40 min)",
    "Cera Medias Piernas": "Depilación con cera de media pierna: pantorrilla o muslo a elegir (30 min)",
    "Abdomen, Glúteos, Espalda o Pecho": "Depilación con cera de una zona a elegir. Resultado limpio y prolijo (30 min)",
    "Cera Muslos": "Depilación con cera de la zona de los muslos. Completa la media pierna (30 min)",
    "Pubis Completo": "Depilación con cera de la zona del pubis al completo (30 min)",
    "Ingles Brasileñas": "Depilación con cera al estilo brasileño: elimina todo el vello de la zona íntima (30 min)",
    "Bioterapia Sculptor Completo": "Tratamiento anticelulítico completo: reduce nódulos y retención de líquidos (60 min)",
    "Bioterapia Podal": "Tratamiento específico para pies: hidrata, revitaliza y alivia la fatiga (40 min)",
    "Limar y Pintar Pies": "Limado + esmaltado estándar de uñas de pies (30 min)",
    "Limar y Pintar Pies Permanente": "Esmaltado permanente de pies. Duración y color que aguanta todo (40 min)",
    "Bioterapia de Manos": "Hidratación y revitalización intensiva de manos. Piel suave y rejuvenecida (45 min)",
    "Pedicura Permanente con Bioterapia": "Pedicura completa + esmaltado permanente + bioterapia para pies en un turno (75 min)",
    "Manicura Caballero": "Manicura profesional para caballeros: limado, cutículas e hidratación (30 min)",
    "Limar y Pintar Manos": "Limado + esmaltado estándar de uñas de manos. Sin tratamiento adicional (30 min)",
    "Labio": "Depilación con cera del labio superior. Resultado suave y duradero (10 min)",
}


def upgrade() -> None:
    # 1. Add price_cents column (nullable, no backfill)
    op.add_column("services", sa.Column("price_cents", sa.Integer(), nullable=True))

    # 2. Rename + improve description, matched by deterministic UUID of OLD name
    for old_name, new_name, new_desc in RENAMES:
        old_id = generate_service_uuid(old_name)
        op.execute(
            sa.text(
                "UPDATE services SET name = :n, description = :d WHERE id = :id"
            ).bindparams(n=new_name, d=new_desc, id=str(old_id))
        )


def downgrade() -> None:
    # 1. Revert names + descriptions to the previous versions
    for old_name, new_name, _new_desc in RENAMES:
        old_id = generate_service_uuid(old_name)
        old_desc = OLD_DESCRIPTIONS[old_name]
        op.execute(
            sa.text(
                "UPDATE services SET name = :n, description = :d WHERE id = :id"
            ).bindparams(n=old_name, d=old_desc, id=str(old_id))
        )

    # 2. Drop price_cents column
    op.drop_column("services", "price_cents")
