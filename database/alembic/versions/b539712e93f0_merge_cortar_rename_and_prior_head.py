"""merge cortar rename and prior head

Revision ID: b539712e93f0
Revises: c1d2e3f4g5h6, w3x4y5z6a7b8
Create Date: 2026-04-22 15:08:45.492993

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b539712e93f0'
down_revision: Union[str, None] = ('c1d2e3f4g5h6', 'w3x4y5z6a7b8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
