"""add conversation_paused_reminder notification type

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-05-11

Hotfix for sdd/conversaciones-inbox PR-3. The PR added the Python enum
value NotificationType.CONVERSATION_PAUSED_REMINDER for the SC-8 daily
reminder handler (paused_24h) but omitted the Postgres ALTER TYPE step.
The notifications worker crashes when the handler tries to insert with
this value.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'conversation_paused_reminder'"
    )


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values directly; leave as no-op.
    pass
