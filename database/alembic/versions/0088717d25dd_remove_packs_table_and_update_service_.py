"""remove_packs_table_and_update_service_category

Revision ID: 0088717d25dd
Revises: bd3989659200
Create Date: 2025-11-03 11:55:54.035767

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0088717d25dd'
down_revision: Union[str, None] = 'bd3989659200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Remove packs table completely.
    The packs functionality is being eliminated in favor of individual services.
    """
    # First, drop the foreign key constraint from appointments table
    op.drop_constraint('appointments_pack_id_fkey', 'appointments', type_='foreignkey')

    # Then drop the pack_id column from appointments
    op.drop_column('appointments', 'pack_id')

    # Finally, drop the packs table
    op.drop_table('packs')


def downgrade() -> None:
    """
    Recreate packs table in case we need to rollback.
    """
    # Recreate packs table with original structure
    op.create_table(
        'packs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('included_service_ids', sa.ARRAY(sa.UUID()), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('price_euros', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # Recreate indexes
    op.create_index('ix_packs_included_service_ids', 'packs', ['included_service_ids'], unique=False, postgresql_using='gin')
    op.create_index('ix_packs_is_active', 'packs', ['is_active'], unique=False)
    op.create_index('ix_packs_name', 'packs', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})

    # Recreate pack_id column in appointments
    op.add_column('appointments', sa.Column('pack_id', sa.UUID(), nullable=True))

    # Recreate foreign key constraint
    op.create_foreign_key('appointments_pack_id_fkey', 'appointments', 'packs', ['pack_id'], ['id'], ondelete='SET NULL')
