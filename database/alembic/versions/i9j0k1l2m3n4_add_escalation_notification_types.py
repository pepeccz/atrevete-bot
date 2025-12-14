"""add escalation notification types for human handoff

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2025-12-13

Adds new notification types for the escalation system (human handoff):
- escalation_manual: User explicitly requested human agent
- escalation_technical: Technical error triggered escalation
- escalation_auto: Auto-escalation after consecutive errors (error_count >= 3)
- escalation_medical: Medical consultation requires human attention
- escalation_ambiguity: Ambiguous request after multiple failed attempts
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new notification types for escalation system
    # PostgreSQL requires ALTER TYPE to add new enum values
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'escalation_manual'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'escalation_technical'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'escalation_auto'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'escalation_medical'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'escalation_ambiguity'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values directly
    # This would require recreating the type and all dependent columns
    # For safety, we leave this as a no-op
    pass
