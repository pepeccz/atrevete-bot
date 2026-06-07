"""add_policy_acceptance — policy_accepted_at + policy_version on customers; customer_consents table

Revision ID: b9d4e8f1c2a3
Revises: c7d8e9f0a1b2
Create Date: 2026-06-07

PR-1 additive migration:
- Adds ``customers.policy_accepted_at`` (TIMESTAMPTZ NULL) — GDPR policy gate timestamp
- Adds ``customers.policy_version`` (VARCHAR(16) NULL) — opaque version string (e.g. "1.0")
- Creates ``customer_consents`` append-only audit table with CHECK on accepted_via
- Creates composite index ix_customer_consents_customer_id_accepted_at

Downgrade reverses all changes in correct dependency order.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "b9d4e8f1c2a3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # --- customers: two new nullable columns ---
    op.add_column(
        "customers",
        sa.Column("policy_accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "customers",
        sa.Column("policy_version", sa.String(16), nullable=True),
    )

    # --- customer_consents: append-only audit table ---
    op.create_table(
        "customer_consents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.String(16), nullable=False),
        sa.Column(
            "accepted_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("accepted_via", sa.String(16), nullable=False),
        sa.Column("source_message_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "accepted_via IN ('whatsapp', 'admin_panel')",
            name="ck_customer_consents_accepted_via",
        ),
    )

    op.create_index(
        "ix_customer_consents_customer_id_accepted_at",
        "customer_consents",
        ["customer_id", "accepted_at"],
        postgresql_using="btree",
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(
        "ix_customer_consents_customer_id_accepted_at",
        table_name="customer_consents",
    )
    op.drop_table("customer_consents")
    op.drop_column("customers", "policy_version")
    op.drop_column("customers", "policy_accepted_at")
