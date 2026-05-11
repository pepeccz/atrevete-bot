"""add can_reply mirror columns to conversation_history

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-05-11

Mirrors Chatwoot's conversation.can_reply (24h WhatsApp window indicator)
into our DB so the admin panel inbox composer can read window state in one
DB hit instead of querying message timestamps or round-tripping to Chatwoot.

Populated by the Chatwoot webhook on every message_created event. Stale
entries (captured > 24h ago) fall back to the timestamp-based computation
in window_service.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_history",
        sa.Column("can_reply", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "conversation_history",
        sa.Column(
            "can_reply_captured_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation_history", "can_reply_captured_at")
    op.drop_column("conversation_history", "can_reply")
