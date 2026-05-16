"""add color column to stylists

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2025-12-10 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g7h8'
down_revision: str | None = 'b2c3d4e5f6g7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('stylists', sa.Column('color', sa.String(7), nullable=True))


def downgrade() -> None:
    op.drop_column('stylists', 'color')
