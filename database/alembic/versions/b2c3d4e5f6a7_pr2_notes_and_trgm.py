"""pr2 — conversation_notes table + pg_trgm GIN indexes for global search

Revision ID: b2c3d4e5f6a7
Revises: pr1msg5b3a7c
Create Date: 2026-05-14

PR-2 additive migration:
- Creates ``conversation_notes`` table (operator notes per conversation)
- Enables ``pg_trgm`` extension (safe idempotent CREATE EXTENSION IF NOT EXISTS)
- Adds trigram GIN indexes on customers.name, customers.phone,
  and conversation_messages.content to accelerate global-search ILIKE queries

Downgrade:
- Drops the three GIN indexes
- Drops the ``conversation_notes`` table + its two indexes
- Leaves pg_trgm installed (shared resource; safer than unconditional DROP)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ─── Revision identifiers ─────────────────────────────────────────────────────

revision: str = "b2c3d4e5f6a7"
down_revision: str = "pr1msg5b3a7c"
branch_labels = None
depends_on = None


# ─── Upgrade ──────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # 1. Enable pg_trgm — safe even if already installed
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2. Create conversation_notes table
    op.create_table(
        "conversation_notes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "conversation_history_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_history.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 3. Indexes on conversation_notes
    op.create_index(
        "idx_conversation_notes_conv",
        "conversation_notes",
        ["conversation_history_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_conversation_notes_author",
        "conversation_notes",
        ["author_user_id"],
    )

    # 4. Trigram GIN indexes for global search
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_customers_name_trgm "
        "ON customers USING GIN (first_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_customers_phone_trgm "
        "ON customers USING GIN (phone gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_messages_content_trgm "
        "ON conversation_messages USING GIN (content gin_trgm_ops)"
    )


# ─── Downgrade ────────────────────────────────────────────────────────────────


def downgrade() -> None:
    # Drop GIN indexes first (on other tables)
    op.execute("DROP INDEX IF EXISTS idx_conv_messages_content_trgm")
    op.execute("DROP INDEX IF EXISTS idx_customers_phone_trgm")
    op.execute("DROP INDEX IF EXISTS idx_customers_name_trgm")

    # Drop conversation_notes indexes then table
    op.drop_index("idx_conversation_notes_author", table_name="conversation_notes")
    op.drop_index("idx_conversation_notes_conv", table_name="conversation_notes")
    op.drop_table("conversation_notes")

    # pg_trgm extension intentionally left installed on downgrade:
    # it is a shared resource and other migrations or queries may depend on it.
