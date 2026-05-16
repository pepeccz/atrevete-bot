"""add_service_metadata_for_disambiguation

Adds a JSONB `metadata` column to the `services` table to support data-driven
service disambiguation. The column stores family membership, clarification
dimensions (audience, hair_length, hair_density), and combo recommendations
per service. Default is an empty object `{}` — all existing rows get the
safe default automatically; only ambiguous-family services are seeded with
structured metadata.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-03-12 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "r8s9t0u1v2w3"
down_revision: str | None = "q7r8s9t0u1v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add `metadata` JSONB column to services table.
    # server_default='{}' ensures existing rows get an empty object without a
    # full table-rewrite; nullable=False is enforced by SQLAlchemy at ORM level.
    op.add_column(
        "services",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("services", "metadata")
