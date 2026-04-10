"""add stripe invoicing columns to invoices

Revision ID: c1d2e3f4g5h6
Revises: b1l2l3i4n5g6
Create Date: 2026-04-10

Adds 6 nullable Stripe Invoicing columns to the invoices table for Spain B2B
fiscal compliance: stripe_invoice_id, invoice_pdf_url, subtotal_eur,
tax_rate_pct, tax_amount_eur, gross_amount_eur. Also adds an index on
stripe_invoice_id for fast lookup. All columns are nullable for backward
compatibility with existing invoices.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c1d2e3f4g5h6"
down_revision = "b1l2l3i4n5g6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Add Stripe Invoicing columns (all nullable — backward compat)
    # ------------------------------------------------------------------
    op.add_column(
        "invoices",
        sa.Column("stripe_invoice_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("invoice_pdf_url", sa.String(500), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("subtotal_eur", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("tax_rate_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("tax_amount_eur", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("gross_amount_eur", sa.Numeric(10, 2), nullable=True),
    )

    # ------------------------------------------------------------------
    # Index on stripe_invoice_id for fast lookup
    # ------------------------------------------------------------------
    op.create_index("idx_invoices_stripe_invoice_id", "invoices", ["stripe_invoice_id"])


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Drop index first, then columns
    # ------------------------------------------------------------------
    op.drop_index("idx_invoices_stripe_invoice_id", table_name="invoices")

    op.drop_column("invoices", "gross_amount_eur")
    op.drop_column("invoices", "tax_amount_eur")
    op.drop_column("invoices", "tax_rate_pct")
    op.drop_column("invoices", "subtotal_eur")
    op.drop_column("invoices", "invoice_pdf_url")
    op.drop_column("invoices", "stripe_invoice_id")
