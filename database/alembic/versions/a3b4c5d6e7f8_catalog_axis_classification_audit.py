"""Catalog axis classification audit

Reclassifies 7 services from variant→addon (parent_service_name → NULL)
and fixes Barro Gold Extra (cross-category mis-parenting under Tratamiento Facial
→ standalone AESTHETICS facial principal).

Revision ID: a3b4c5d6e7f8
Revises:     f0a1b2c3d4e5
Create Date: 2026-05-11

Changes (REQ-DR-1 through REQ-DR-8):
  - Tinte Extra:                                 variant → addon, parent → NULL
  - Mechas Extras:                               variant → addon, parent → NULL
  - Barro Extra:                                 variant → addon, parent → NULL
  - Tratamiento Facial + Radiofrecuencia (15 min): variant → addon, parent → NULL
  - Tratamiento Facial + Radiofrecuencia (30 min): variant → addon, parent → NULL
  - Tratamiento Anticelulítico + Radiofrecuencia (30 min): variant → addon, parent → NULL
  - Piernas Perfectas + Presoterapia (30 min):   variant → addon, parent → NULL
  - Barro Gold Extra:                            variant (AESTHETICS) → standalone principal,
                                                  parent → NULL, dimension → facial
                                                  (was incorrectly parented under
                                                  'Tratamiento Facial'; design I-1 concluded
                                                  this is a distinct AESTHETICS facial offering)

Idempotency: each UPDATE sets fields to constant values; re-running upgrade on an
already-migrated DB produces zero row changes (the WHERE clause matches rows in their
original state only when the service_type guard is present; for reclassified rows the
jsonb_set is always idempotent to the target value).

Downgrade: restores all 8 rows to their original variant/parent state.

Verification (run on test DB post-upgrade):
  SELECT name, metadata->>'service_type', metadata->>'parent_service_name'
  FROM services
  WHERE name IN (
    'Tinte Extra', 'Mechas Extras', 'Barro Extra',
    'Tratamiento Facial + Radiofrecuencia (15 min)',
    'Tratamiento Facial + Radiofrecuencia (30 min)',
    'Tratamiento Anticelulítico + Radiofrecuencia (30 min)',
    'Piernas Perfectas + Presoterapia (30 min)',
    'Barro Gold Extra'
  );
  -- Expected: service_type=addon (or principal for Barro Gold Extra),
  --           parent_service_name=null for all 8 rows.
"""

from alembic import op

# revision identifiers, used by Alembic
revision = "a3b4c5d6e7f8"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None

# 7 services reclassified: variant → addon
_RECLASSIFIED_ADDONS: list[str] = [
    "Tinte Extra",
    "Mechas Extras",
    "Barro Extra",
    "Tratamiento Facial + Radiofrecuencia (15 min)",
    "Tratamiento Facial + Radiofrecuencia (30 min)",
    "Tratamiento Anticelulítico + Radiofrecuencia (30 min)",
    "Piernas Perfectas + Presoterapia (30 min)",
]

# Original (variant) state for downgrade — name → original parent_service_name
_ORIGINAL_PARENTS: dict[str, str] = {
    "Tinte Extra": "Tinte",
    "Mechas Extras": "Mechas",
    "Barro Extra": "Barro",
    "Tratamiento Facial + Radiofrecuencia (15 min)": "Tratamiento Facial",
    "Tratamiento Facial + Radiofrecuencia (30 min)": "Tratamiento Facial",
    "Tratamiento Anticelulítico + Radiofrecuencia (30 min)": "Tratamiento Anticelulítico Completo",
    "Piernas Perfectas + Presoterapia (30 min)": "Tratamiento Anticelulítico Completo",
}


def upgrade() -> None:
    # 1. Reclassify 7 duration-delta variants: variant → addon, clear parent
    for name in _RECLASSIFIED_ADDONS:
        op.execute(
            f"""
            UPDATE services
            SET metadata = jsonb_set(
                jsonb_set(metadata, '{{service_type}}', '"addon"'::jsonb),
                '{{parent_service_name}}', 'null'::jsonb
            )
            WHERE name = '{name}'
            """
        )

    # 2. Fix Barro Gold Extra: cross-category mis-parent → standalone AESTHETICS principal
    #    The service is an AESTHETICS (category) facial offering (dimension=facial).
    #    It was incorrectly parented under 'Tratamiento Facial' — a data error.
    #    Design decision I-1: reclassify as principal with dimension=facial (not a child
    #    of HAIRDRESSING 'Barro Gold'; their shared name prefix is coincidental branding).
    op.execute("""
        UPDATE services
        SET metadata = jsonb_set(
            jsonb_set(
                jsonb_set(metadata, '{service_type}', '"principal"'::jsonb),
                '{parent_service_name}', 'null'::jsonb
            ),
            '{dimension}', '"facial"'::jsonb
        )
        WHERE name = 'Barro Gold Extra'
    """)


def downgrade() -> None:
    # Reverse Barro Gold Extra: standalone principal → variant under Tratamiento Facial
    op.execute("""
        UPDATE services
        SET metadata = jsonb_set(
            jsonb_set(
                jsonb_set(metadata, '{service_type}', '"variant"'::jsonb),
                '{parent_service_name}', '"Tratamiento Facial"'::jsonb
            ),
            '{dimension}', '"facial"'::jsonb
        )
        WHERE name = 'Barro Gold Extra'
    """)

    # Restore 7 reclassified services: addon → variant, restore original parent
    for name, parent in _ORIGINAL_PARENTS.items():
        op.execute(
            f"""
            UPDATE services
            SET metadata = jsonb_set(
                jsonb_set(metadata, '{{service_type}}', '"variant"'::jsonb),
                '{{parent_service_name}}', '"{parent}"'::jsonb
            )
            WHERE name = '{name}'
            """
        )
