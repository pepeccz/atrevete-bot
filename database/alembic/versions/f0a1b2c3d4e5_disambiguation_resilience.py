"""Disambiguation resilience: reclassify Flequillo, Barba, Perilla, Manicura de Hombre

Revision ID: f0a1b2c3d4e5
Revises: f7e8d9c0b1a2
Create Date: 2026-05-11

PR-1: Slice 1 — data-reclassification for disambiguation-resilience change.

Changes (REQ-DR-1, REQ-DR-2, REQ-DR-3):
- Corte de Flequillo: variant (child of Corte de Mujer) → principal (independent cut)
- Barba: variant (child of Corte de Hombre) → addon (standalone grooming service)
- Perilla: variant (child of Corte de Hombre) → addon (standalone grooming service)
- Manicura de Hombre: variant (child of Manicura) → principal with audience=adult_male

REQ-DR-4 (Tratamiento Precolor): VOID — already correctly classified as addon,
dimension=color, parent_service_name=None (confirmed in design I-1).

NFR-4: All UPDATE statements are idempotent. Running upgrade twice produces no error.
Downgrade restores original classification for all 4 rows.
"""

from alembic import op

# revision identifiers, used by Alembic
revision = "f0a1b2c3d4e5"
down_revision = "f7e8d9c0b1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Corte de Flequillo: variant → principal, clear parent_service_name
    op.execute("""
        UPDATE services
        SET metadata = jsonb_set(
            jsonb_set(metadata, '{service_type}', '"principal"'::jsonb),
            '{parent_service_name}', 'null'::jsonb
        )
        WHERE name = 'Corte de Flequillo'
    """)

    # 2. Barba: variant → addon, clear parent_service_name
    op.execute("""
        UPDATE services
        SET metadata = jsonb_set(
            jsonb_set(metadata, '{service_type}', '"addon"'::jsonb),
            '{parent_service_name}', 'null'::jsonb
        )
        WHERE name = 'Barba'
    """)

    # 3. Perilla: variant → addon, clear parent_service_name
    op.execute("""
        UPDATE services
        SET metadata = jsonb_set(
            jsonb_set(metadata, '{service_type}', '"addon"'::jsonb),
            '{parent_service_name}', 'null'::jsonb
        )
        WHERE name = 'Perilla'
    """)

    # 4. Manicura de Hombre: variant → principal, audience=adult_male, clear parent_service_name
    op.execute("""
        UPDATE services
        SET audience = 'adult_male',
            metadata = jsonb_set(
                jsonb_set(metadata, '{service_type}', '"principal"'::jsonb),
                '{parent_service_name}', 'null'::jsonb
            )
        WHERE name = 'Manicura de Hombre'
    """)

    # Tratamiento Precolor: VOID — already addon, dimension=color, parent_service_name=None


def downgrade() -> None:
    # Revert in reverse order. Restore original classification for all 4 rows.

    # 4. Manicura de Hombre: principal → variant, restore audience, restore parent
    op.execute("""
        UPDATE services
        SET audience = 'adult_male',
            metadata = jsonb_set(
                jsonb_set(metadata, '{service_type}', '"variant"'::jsonb),
                '{parent_service_name}', '"Manicura"'::jsonb
            )
        WHERE name = 'Manicura de Hombre'
    """)

    # 3. Perilla: addon → variant, restore parent
    op.execute("""
        UPDATE services
        SET metadata = jsonb_set(
            jsonb_set(metadata, '{service_type}', '"variant"'::jsonb),
            '{parent_service_name}', '"Corte de Hombre"'::jsonb
        )
        WHERE name = 'Perilla'
    """)

    # 2. Barba: addon → variant, restore parent
    op.execute("""
        UPDATE services
        SET metadata = jsonb_set(
            jsonb_set(metadata, '{service_type}', '"variant"'::jsonb),
            '{parent_service_name}', '"Corte de Hombre"'::jsonb
        )
        WHERE name = 'Barba'
    """)

    # 1. Corte de Flequillo: principal → variant, restore parent
    op.execute("""
        UPDATE services
        SET metadata = jsonb_set(
            jsonb_set(metadata, '{service_type}', '"variant"'::jsonb),
            '{parent_service_name}', '"Corte de Mujer"'::jsonb
        )
        WHERE name = 'Corte de Flequillo'
    """)
