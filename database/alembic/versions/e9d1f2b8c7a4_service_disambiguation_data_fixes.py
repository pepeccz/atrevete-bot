"""service_disambiguation_data_fixes

Revision ID: e9d1f2b8c7a4
Revises: a7b8c9d0e1f2
Create Date: 2026-05-11

PR-1: Slice 1 — data-fixes for service-disambiguation-and-booking-ux

Changes:
- Tinte.audience = 'adult_female' (was NULL; needed for audience disambiguation gate)
- Rename principal "Depilación de Piernas Enteras" → "Depilación" (UUID unchanged)
- Update all 11 child variant rows: metadata_[parent_service_name] patched via jsonb_set
- Insert new "Piernas Enteras" variant (12th wax variant, child of "Depilación")

NFR-3: UUID of the renamed principal row is NOT changed. Existing FK references remain valid.
NFR-4: All UPDATE statements are idempotent (WHERE clauses match old value only).

NOTE: Original revision ID a7b8c9d0e1f2 collided with an existing migration
(drop_stripe_payment_link_id_from_appointments) that was already applied to
production. Re-keyed to e9d1f2b8c7a4 and re-parented to a7b8c9d0e1f2 (the
actual head on production at the time of writing).
"""

from alembic import op

# revision identifiers, used by Alembic
revision = "e9d1f2b8c7a4"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Tag Tinte with adult_female audience (was NULL)
    op.execute(
        "UPDATE services SET audience = 'adult_female' WHERE name = 'Tinte' AND audience IS NULL"
    )

    # 2. Rename the wax principal: "Depilación de Piernas Enteras" → "Depilación"
    #    UUID is preserved; only name and description change.
    op.execute("""
        UPDATE services
        SET name = 'Depilación',
            description = 'Depilación con cera. Elige la zona corporal (40 min para piernas enteras)'
        WHERE name = 'Depilación de Piernas Enteras'
          AND metadata_->>'service_type' = 'principal'
        """)

    # 3. Patch all 11 child variant rows: parent_service_name string inside JSONB
    op.execute("""
        UPDATE services
        SET metadata_ = jsonb_set(metadata_, '{parent_service_name}', '"Depilación"'::jsonb)
        WHERE metadata_->>'parent_service_name' = 'Depilación de Piernas Enteras'
        """)

    # 4. Insert "Piernas Enteras" as the 12th wax variant (child of renamed principal)
    op.execute("""
        INSERT INTO services (
            id, name, category, duration_minutes, description,
            audience, metadata_, is_active, created_at, updated_at
        )
        VALUES (
            gen_random_uuid(),
            'Piernas Enteras',
            'aesthetics',
            40,
            'Depilación con cera de piernas enteras: desde tobillo hasta ingle (40 min)',
            NULL,
            '{"service_type": "variant", "dimension": "wax", "parent_service_name": "Depilación"}'::jsonb,
            true,
            now(),
            now()
        )
        """)


def downgrade() -> None:
    # Reverse in reverse order

    # 4. Remove the "Piernas Enteras" variant inserted by upgrade
    op.execute("""
        DELETE FROM services
        WHERE name = 'Piernas Enteras'
          AND metadata_->>'parent_service_name' = 'Depilación'
          AND metadata_->>'service_type' = 'variant'
        """)

    # 3. Revert child variant parent_service_name back to old name
    op.execute("""
        UPDATE services
        SET metadata_ = jsonb_set(
            metadata_,
            '{parent_service_name}',
            '"Depilación de Piernas Enteras"'::jsonb
        )
        WHERE metadata_->>'parent_service_name' = 'Depilación'
          AND metadata_->>'service_type' = 'variant'
          AND metadata_->>'dimension' = 'wax'
        """)

    # 2. Revert principal name back
    op.execute("""
        UPDATE services
        SET name = 'Depilación de Piernas Enteras',
            description = 'Depilación con cera de piernas enteras: desde tobillo hasta ingle, ambas piernas completas (40 min)'
        WHERE name = 'Depilación'
          AND metadata_->>'service_type' = 'principal'
        """)

    # 1. Revert Tinte audience back to NULL
    op.execute(
        "UPDATE services SET audience = NULL WHERE name = 'Tinte' AND audience = 'adult_female'"
    )
