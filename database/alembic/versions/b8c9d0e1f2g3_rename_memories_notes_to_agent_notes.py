"""rename memories.notes to memories.agent_notes

Revision ID: a1b2c3d4e5f6
Revises: z6a7b8c9d0e1
Create Date: 2026-05-10

Data-only migration: renames the JSONB sub-key memories.notes -> memories.agent_notes
for all customers rows. Idempotent. Symmetric downgrade.
"""

from alembic import op

revision: str = "b8c9d0e1f2g3"
down_revision: str | None = "c9d0e1f2g3h4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE customers
        SET metadata =
            jsonb_set(
                metadata #- '{memories,notes}',
                '{memories,agent_notes}',
                metadata->'memories'->'notes',
                true
            )
        WHERE metadata ? 'memories'
          AND metadata->'memories' ? 'notes'
          AND NOT (metadata->'memories' ? 'agent_notes');
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE customers
        SET metadata =
            jsonb_set(
                metadata #- '{memories,agent_notes}',
                '{memories,notes}',
                metadata->'memories'->'agent_notes',
                true
            )
        WHERE metadata ? 'memories'
          AND metadata->'memories' ? 'agent_notes'
          AND NOT (metadata->'memories' ? 'notes');
    """)
