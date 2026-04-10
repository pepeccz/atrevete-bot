"""add billing tables (invoices and payments)

Revision ID: b1l2l3i4n5g6
Revises: v2w3x4y5z6a7
Create Date: 2026-04-10

Creates invoice_status and payment_status enum types, the invoices and payments
tables, a partial unique index enforcing one active invoice per (year, month),
and all supporting indexes.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b1l2l3i4n5g6"
down_revision = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create PostgreSQL enum types
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TYPE invoice_status AS ENUM (
            'draft', 'issued', 'paid', 'overdue', 'void'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE payment_status AS ENUM (
            'pending', 'processing', 'succeeded', 'failed', 'refunded'
        )
        """
    )

    # ------------------------------------------------------------------
    # 2. Create invoices table
    # ------------------------------------------------------------------
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_number", sa.String(20), unique=True, nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("maintenance_amount_eur", sa.Numeric(10, 2), nullable=False),
        sa.Column("token_amount_eur", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_amount_eur", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "issued",
                "paid",
                "overdue",
                "void",
                name="invoice_status",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("issued_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("pdf_path", sa.String(500), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(100), nullable=True),
        sa.Column(
            "token_usage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("token_usage.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 3. Create payments table
    # ------------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stripe_payment_intent_id", sa.String(100), unique=True, nullable=False),
        sa.Column("stripe_charge_id", sa.String(100), nullable=True),
        sa.Column("amount_eur", sa.Numeric(10, 2), nullable=False),
        sa.Column("stripe_fee_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "succeeded",
                "failed",
                "refunded",
                name="payment_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("payment_method", sa.String(50), nullable=False, server_default="sepa_debit"),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # 4. Partial unique index — one active invoice per (year, month)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX uq_active_invoice_year_month
        ON invoices(year, month)
        WHERE status != 'void'
        """
    )

    # ------------------------------------------------------------------
    # 5. Regular indexes
    # ------------------------------------------------------------------
    op.create_index("idx_invoices_status", "invoices", ["status"])
    op.create_index("idx_invoices_year_month", "invoices", ["year", "month"])
    op.create_index("idx_payments_invoice_id", "payments", ["invoice_id"])
    op.create_index("idx_payments_stripe_pi", "payments", ["stripe_payment_intent_id"])


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Drop indexes
    # ------------------------------------------------------------------
    op.drop_index("idx_payments_stripe_pi", table_name="payments")
    op.drop_index("idx_payments_invoice_id", table_name="payments")
    op.drop_index("idx_invoices_year_month", table_name="invoices")
    op.drop_index("idx_invoices_status", table_name="invoices")
    op.execute("DROP INDEX IF EXISTS uq_active_invoice_year_month")

    # ------------------------------------------------------------------
    # Drop tables
    # ------------------------------------------------------------------
    op.drop_table("payments")
    op.drop_table("invoices")

    # ------------------------------------------------------------------
    # Drop enum types
    # ------------------------------------------------------------------
    op.execute("DROP TYPE IF EXISTS payment_status")
    op.execute("DROP TYPE IF EXISTS invoice_status")
