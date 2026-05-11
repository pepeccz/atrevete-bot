"""realign_variant_parent_names

Revision ID: f7e8d9c0b1a2
Revises: e9d1f2b8c7a4
Create Date: 2026-05-11

Follow-up to PR-1 (service-disambiguation-and-booking-ux): production
DB carries a pre-existing data drift where principals were renamed to
natural names (in seeds + DB) but their child variants' JSONB
`parent_service_name` was never updated to match. Result: 26 variants
across 9 groups point at parents that no longer exist by that name.

This migration aligns the variant parents to the current principal
names. Discovered while applying PR-1 (Cera Enteras → Depilación was
the trigger).

Mapping (old → new):
  Cera Enteras                  → Depilación
  Corte Caballero               → Corte de Hombre
  Corte Dama                    → Corte de Mujer
  Cultura de Color              → Tinte
  Limar y Pintar Manos          → Manicura
  Limar y Pintar Pies           → Pedicura
  Bioterapia Facial             → Tratamiento Facial
  Bioterapia Sculptor Completo  → Tratamiento Anticelulítico Completo
  Bioterapia de Senos           → Tratamiento de Senos

All UPDATEs are idempotent (WHERE matches old value only). Downgrade
reverses each mapping.
"""

from alembic import op

revision = "f7e8d9c0b1a2"
down_revision = "e9d1f2b8c7a4"
branch_labels = None
depends_on = None


# (old_name, new_name) — order is irrelevant; WHEREs are mutually exclusive
_RENAMES = [
    ("Cera Enteras", "Depilación"),
    ("Corte Caballero", "Corte de Hombre"),
    ("Corte Dama", "Corte de Mujer"),
    ("Cultura de Color", "Tinte"),
    ("Limar y Pintar Manos", "Manicura"),
    ("Limar y Pintar Pies", "Pedicura"),
    ("Bioterapia Facial", "Tratamiento Facial"),
    ("Bioterapia Sculptor Completo", "Tratamiento Anticelulítico Completo"),
    ("Bioterapia de Senos", "Tratamiento de Senos"),
]


def upgrade() -> None:
    for old, new in _RENAMES:
        op.execute(
            f"""
            UPDATE services
            SET metadata = jsonb_set(metadata, '{{parent_service_name}}', '"{new}"'::jsonb)
            WHERE metadata->>'parent_service_name' = '{old}'
            """
        )


def downgrade() -> None:
    for old, new in _RENAMES:
        op.execute(
            f"""
            UPDATE services
            SET metadata = jsonb_set(metadata, '{{parent_service_name}}', '"{old}"'::jsonb)
            WHERE metadata->>'parent_service_name' = '{new}'
              AND metadata->>'service_type' = 'variant'
            """
        )
