"""Rename service 'Cortar' to 'Corte Dama' and tag women's-only services with audience.

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-04-22

Changes:
1. Rename "Cortar" → "Corte Dama" in the services table.
2. Update the parent_service_name reference in variants that point to "Cortar".
3. Ensure all women's-only (adult_female) services have audience='adult_female' set.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "w3x4y5z6a7b8"
down_revision: Union[str, None] = "v2w3x4y5z6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename "Cortar" → "Corte Dama"
    op.execute(
        sa.text("UPDATE services SET name = 'Corte Dama' WHERE name = 'Cortar'")
    )

    # 2. Update metadata_ JSONB: variants whose parent_service_name = "Cortar"
    #    must now reference "Corte Dama"
    op.execute(
        sa.text(
            """
            UPDATE services
            SET metadata = jsonb_set(
                metadata,
                '{parent_service_name}',
                '"Corte Dama"'
            )
            WHERE metadata ->> 'parent_service_name' = 'Cortar'
            """
        )
    )

    # 3. Tag all women's-only services with audience = 'adult_female'
    #    This covers services in metadata_ that have audience = "adult_female"
    #    but the top-level column was not set.
    op.execute(
        sa.text(
            """
            UPDATE services
            SET audience = 'adult_female'
            WHERE (metadata ->> 'audience' = 'adult_female'
                   OR name IN (
                       'Corte Dama', 'Corte + Secado Dama', 'Tinte Completo',
                       'Mechas', 'Balayage', 'Permanente', 'Alisado Keratina',
                       'Tratamiento Hidratante', 'Lifting de Pestañas',
                       'Extensiones de Pestañas', 'Manicura', 'Pedicura',
                       'Manicura + Pedicura', 'Manicura Semipermanente',
                       'Pedicura Semipermanente', 'Depilación'
                   ))
              AND (audience IS NULL OR audience != 'adult_female')
            """
        )
    )


def downgrade() -> None:
    # 1. Revert audience tags added by this migration
    #    (only revert if they were NULL before — safest approximation)
    # NOTE: This is a best-effort downgrade; data-only migrations are hard to reverse exactly.

    # 2. Revert metadata_ parent_service_name back to "Cortar"
    op.execute(
        sa.text(
            """
            UPDATE services
            SET metadata = jsonb_set(
                metadata,
                '{parent_service_name}',
                '"Cortar"'
            )
            WHERE metadata ->> 'parent_service_name' = 'Corte Dama'
            """
        )
    )

    # 3. Revert "Corte Dama" → "Cortar"
    op.execute(
        sa.text("UPDATE services SET name = 'Cortar' WHERE name = 'Corte Dama'")
    )
