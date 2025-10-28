"""make_conversation_history_customer_id_nullable

Revision ID: 1f737760963f
Revises: de6f4bde8b7
Create Date: 2025-10-28 17:41:43.499409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f737760963f'
down_revision: Union[str, None] = 'de6f4bde8b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make customer_id nullable to allow archival of conversations from unidentified customers
    op.alter_column('conversation_history', 'customer_id',
                    existing_type=sa.UUID(),
                    nullable=True)


def downgrade() -> None:
    # Revert customer_id to non-nullable (requires all rows to have customer_id)
    op.alter_column('conversation_history', 'customer_id',
                    existing_type=sa.UUID(),
                    nullable=False)
