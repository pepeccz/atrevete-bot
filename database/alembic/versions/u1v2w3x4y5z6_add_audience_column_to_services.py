"""Add audience column to services table

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-04-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'u1v2w3x4y5z6'
down_revision: Union[str, None] = 'b0c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add audience column
    op.add_column('services', sa.Column('audience', sa.String(30), nullable=True))

    # 2. Backfill from metadata_ JSONB
    op.execute("UPDATE services SET audience = metadata_->>'audience' WHERE metadata_->>'audience' IS NOT NULL")

    # 3. Create partial index on active services
    op.create_index(
        'idx_services_audience',
        'services',
        ['audience'],
        postgresql_where=sa.text('is_active = true'),
    )

    # 4. Drop old GIN trigram index (if exists)
    op.execute("DROP INDEX IF EXISTS idx_services_name_trgm")


def downgrade() -> None:
    op.execute(
        "UPDATE services SET metadata_ = jsonb_set(COALESCE(metadata_, '{}'::jsonb), '{audience}', to_jsonb(audience)) WHERE audience IS NOT NULL"
    )
    op.drop_index('idx_services_audience', table_name='services')
    op.drop_column('services', 'audience')
