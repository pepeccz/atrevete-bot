"""add inbox columns: author_user_id on conversation_messages, pause/resume timestamps on conversation_history

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-05-11

Adds:
- conversation_messages.author_user_id UUID NULL FK → admin_users(id) ON DELETE SET NULL
  with index ix_conversation_messages_author_user
- conversation_history.paused_at TIMESTAMPTZ NULL
- conversation_history.resumed_at TIMESTAMPTZ NULL
- conversation_history.context_injected_at TIMESTAMPTZ NULL

No CHECK constraint on ConversationMessage.role (ADR-3: app-layer enum validation only).
All new columns nullable — existing rows require no backfill.

Deploy runbook: run alembic upgrade head then restart api + agent containers.
No checkpoint flush required (additive nullable columns, thread_id format unchanged).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# revision identifiers, used by Alembic.
revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add author_user_id column to conversation_messages
    op.add_column(
        "conversation_messages",
        sa.Column("author_user_id", PGUUID(as_uuid=True), nullable=True),
    )

    # 2. Add FK constraint: conversation_messages.author_user_id → admin_users.id ON DELETE SET NULL
    op.create_foreign_key(
        "fk_conversation_messages_author_user",
        "conversation_messages",
        "admin_users",
        ["author_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Add index on author_user_id for efficient lookup (e.g. "messages by this admin")
    op.create_index(
        "ix_conversation_messages_author_user",
        "conversation_messages",
        ["author_user_id"],
    )

    # 4. Add paused_at to conversation_history
    op.add_column(
        "conversation_history",
        sa.Column("paused_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # 5. Add resumed_at to conversation_history
    op.add_column(
        "conversation_history",
        sa.Column("resumed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # 6. Add context_injected_at to conversation_history (idempotency guard for resume injection)
    op.add_column(
        "conversation_history",
        sa.Column("context_injected_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Reverse in reverse order of upgrade

    # 6. Drop context_injected_at
    op.drop_column("conversation_history", "context_injected_at")

    # 5. Drop resumed_at
    op.drop_column("conversation_history", "resumed_at")

    # 4. Drop paused_at
    op.drop_column("conversation_history", "paused_at")

    # 3. Drop index on author_user_id
    op.drop_index("ix_conversation_messages_author_user", table_name="conversation_messages")

    # 2. Drop FK constraint
    op.drop_constraint(
        "fk_conversation_messages_author_user",
        "conversation_messages",
        type_="foreignkey",
    )

    # 1. Drop author_user_id column
    op.drop_column("conversation_messages", "author_user_id")
