"""datetime tz-aware uniform — add server_default=now() to Pattern A timestamps

Revision ID: b2c3d4e5f6g7
Revises: z6a7b8c9d0e1
Create Date: 2026-05-10

Adds DB-level DEFAULT now() to the 5 Pattern A tables (stylists, customers,
services, appointments, policies) which previously had no server_default on
their created_at / updated_at columns. This is a metadata-only DDL change on
Postgres — instant, no table rewrite, no row scan.

Pattern B/C tables (business_hours, recurring_blocking_series, blocking_events,
holidays, notifications, system_settings, system_settings_history,
gcal_sync_state, invoices, payments) already have DEFAULT CURRENT_TIMESTAMP
set from their original creation migrations. Their ORM-side change
(text("CURRENT_TIMESTAMP") → func.now(), onupdate=datetime.utcnow → lambda)
is Python-only and produces no DDL.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, None] = "z6a7b8c9d0e1"
branch_labels = None
depends_on = None

# Pattern A tables that currently have NO server_default on their timestamps.
# Each entry: (table_name, [column_names_to_alter])
PATTERN_A = [
    ("stylists", ["created_at", "updated_at"]),
    ("customers", ["created_at"]),
    ("services", ["created_at", "updated_at"]),
    ("appointments", ["created_at", "updated_at"]),
    ("policies", ["created_at", "updated_at"]),
]


def upgrade() -> None:
    for table, cols in PATTERN_A:
        for col in cols:
            op.alter_column(
                table,
                col,
                server_default=sa.text("now()"),
                existing_type=sa.TIMESTAMP(timezone=True),
                existing_nullable=False,
            )


def downgrade() -> None:
    for table, cols in PATTERN_A:
        for col in cols:
            op.alter_column(
                table,
                col,
                server_default=None,
                existing_type=sa.TIMESTAMP(timezone=True),
                existing_nullable=False,
            )
