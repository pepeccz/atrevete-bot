"""rename memories.notes to memories.agent_notes

Revision ID: a1b2c3d4e5f6
Revises: z6a7b8c9d0e1
Create Date: 2026-05-10

Data-only migration: renames the JSONB sub-key memories.notes -> memories.agent_notes
for all customers rows. Idempotent. Symmetric downgrade.
"""

from alembic import op

revision: str = "b8c9d0e1f2g3"
down_revision: str | None = "z6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE customers
        SET metadata_ =
            jsonb_set(
                metadata_ #- '{memories,notes}',
                '{memories,agent_notes}',
                metadata_->'memories'->'notes',
                true
            )
        WHERE metadata_ ? 'memories'
          AND metadata_->'memories' ? 'notes'
          AND NOT (metadata_->'memories' ? 'agent_notes');
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE customers
        SET metadata_ =
            jsonb_set(
                metadata_ #- '{memories,agent_notes}',
                '{memories,notes}',
                metadata_->'memories'->'agent_notes',
                true
            )
        WHERE metadata_ ? 'memories'
          AND metadata_->'memories' ? 'agent_notes'
          AND NOT (metadata_->'memories' ? 'notes');
    """)
