"""merge cortar rename and prior head

Revision ID: b539712e93f0
Revises: c1d2e3f4g5h6, w3x4y5z6a7b8
Create Date: 2026-04-22 15:08:45.492993

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'b539712e93f0'
down_revision: str | None = ('c1d2e3f4g5h6', 'w3x4y5z6a7b8')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
