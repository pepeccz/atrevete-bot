"""merge confirmation settings and reminder retry heads

Revision ID: t0u1v2w3x4y5
Revises: n5o6p7q8r9s0, s9t0u1v2w3x4
Create Date: 2026-03-27 22:00:00.000000

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 't0u1v2w3x4y5'
down_revision: str | None = ('n5o6p7q8r9s0', 's9t0u1v2w3x4')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
