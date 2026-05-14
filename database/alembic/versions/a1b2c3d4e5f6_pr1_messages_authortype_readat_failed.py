"""pr1 — add author_type, read_at, delivery_failed to conversation_messages

Revision ID: a1b2c3d4e5f6
Revises: z6a7b8c9d0e1
Create Date: 2026-05-14

Additive migration for PR-1 foundation:
- author_type VARCHAR(20): canonical author label (bot | human_agent | system | user)
- read_at TIMESTAMPTZ NULL: operator read-receipt timestamp
- delivery_failed BOOLEAN NOT NULL DEFAULT FALSE: Chatwoot delivery failure flag

Backfill derives author_type from existing role values:
  role='user'         -> author_type='user'
  role='human_agent'  -> author_type='human_agent'
  role='system'       -> author_type='system'
  anything else       -> author_type='bot'  (covers role='assistant')

Partial index on (conversation_history_id) WHERE read_at IS NULL
accelerates the mark-read query (only unread rows).
"""


import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "z6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns
    op.add_column(
        "conversation_messages",
        sa.Column("author_type", sa.String(20), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column(
            "delivery_failed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Backfill author_type from role
    op.execute(
        sa.text(
            """
            UPDATE conversation_messages
            SET author_type = CASE role
                WHEN 'user'         THEN 'user'
                WHEN 'human_agent'  THEN 'human_agent'
                WHEN 'system'       THEN 'system'
                ELSE 'bot'
            END
            WHERE author_type IS NULL
            """
        )
    )

    # Partial index: accelerates mark-read query (only rows with read_at IS NULL)
    op.create_index(
        "idx_conversation_messages_unread",
        "conversation_messages",
        ["conversation_history_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_conversation_messages_unread",
        table_name="conversation_messages",
    )
    op.drop_column("conversation_messages", "delivery_failed")
    op.drop_column("conversation_messages", "read_at")
    op.drop_column("conversation_messages", "author_type")
