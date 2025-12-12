"""add confirmation system notification types

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2025-12-11

Adds new notification types for the appointment confirmation system:
- confirmation_sent: 48h confirmation request sent
- confirmation_received: Customer confirmed appointment
- auto_cancelled: Auto-cancelled due to no response
- confirmation_failed: Failed to send confirmation template
- reminder_sent: 2h reminder sent
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new notification types for confirmation system
    # PostgreSQL requires ALTER TYPE to add new enum values
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'confirmation_sent'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'confirmation_received'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'auto_cancelled'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'confirmation_failed'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'reminder_sent'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values directly
    # This would require recreating the type and all dependent columns
    # For safety, we leave this as a no-op
    pass
