"""drop_stripe_payment_link_id_from_appointments

Revision ID: a1b2c3d4e5f6
Revises: z6a7b8c9d0e1
Create Date: 2026-05-10

The column appointments.stripe_payment_link_id is an orphan from the
v1 PaymentIntent flow that was never referenced by any service, route,
or ORM model after the Stripe Invoicing migration.  Removing it keeps
the schema clean.

Pre-merge guard (run on production BEFORE merging this migration):
  SELECT COUNT(*) FROM invoices
  WHERE stripe_payment_intent_id IS NOT NULL
    AND stripe_invoice_id IS NULL
    AND status NOT IN ('paid', 'void');
The count must be 0 before dead-code removal (T8).  This migration itself
is safe regardless of that count — it only touches the appointments table.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "b8c9d0e1f2g3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("appointments")}
    if "stripe_payment_link_id" in cols:
        op.drop_column("appointments", "stripe_payment_link_id")


def downgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("stripe_payment_link_id", sa.String(length=255), nullable=True),
    )
