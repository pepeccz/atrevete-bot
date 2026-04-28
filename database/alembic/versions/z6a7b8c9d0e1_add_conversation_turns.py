"""add conversation_turns table

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-04-28

Adds the conversation_turns table for per-turn observability telemetry:
- latency_ms, tokens_in, tokens_out, tool_calls (JSONB)
- CASCADE DELETE from conversation_history
- Composite index + UNIQUE constraint on (conversation_history_id, turn_number)
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "z6a7b8c9d0e1"
down_revision: Union[str, None] = "y5z6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_history_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_history_id"],
            ["conversation_history.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_history_id",
            "turn_number",
            name="uq_conversation_turns_conv_turn",
        ),
    )
    op.create_index(
        "idx_conversation_turns_conv_turn",
        "conversation_turns",
        ["conversation_history_id", "turn_number"],
    )
    # Explicit FK-column index for fast DELETE CASCADE lookups
    op.create_index(
        "idx_conversation_turns_conv_hist_id",
        "conversation_turns",
        ["conversation_history_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_conversation_turns_conv_hist_id", table_name="conversation_turns")
    op.drop_index("idx_conversation_turns_conv_turn", table_name="conversation_turns")
    op.drop_table("conversation_turns")
