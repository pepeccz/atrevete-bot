"""add admin_users table and escalation resolved_by FK

Revision ID: a4b5c6d7e8f9
Revises: a3b4c5d6e7f8
Create Date: 2026-05-11

Adds:
- admin_users table (UUID PK, username unique, password_hash, role CHECK, is_active,
  display_name nullable, last_login_at nullable, created_at, updated_at)
- Idempotent seed step: inserts one admin user from ADMIN_USERNAME + ADMIN_PASSWORD_HASH
  env vars IF AND ONLY IF admin_users is empty at migration time.
  Fails loudly (RuntimeError) if env vars are missing during seed (FR-DB-6).
- Escalation.resolved_by_user_id UUID NULL FK → admin_users.id ON DELETE SET NULL

deploy runbook: set ADMIN_USERNAME and ADMIN_PASSWORD_HASH env vars before running.
Generate hash with: python -c "import bcrypt; print(bcrypt.hashpw(b'your_pw', bcrypt.gensalt(rounds=12)).decode())"
"""

from __future__ import annotations

import os
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create admin_users table
    op.create_table(
        "admin_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column(
            "last_login_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("role IN ('admin','stylist')", name="admin_users_role_check"),
    )

    # 2. Indexes on admin_users
    op.create_index(
        "ix_admin_users_username",
        "admin_users",
        ["username"],
        unique=True,
    )
    op.create_index(
        "ix_admin_users_role_active",
        "admin_users",
        ["role", "is_active"],
    )

    # 3. Add resolved_by_user_id FK column to escalations
    op.add_column(
        "escalations",
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_escalations_resolved_by_user",
        "escalations",
        "admin_users",
        ["resolved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_escalations_resolved_by",
        "escalations",
        ["resolved_by_user_id"],
    )

    # 4. Idempotent seed step (FR-DB-3, FR-DB-4, FR-DB-6, NFR-5)
    #
    # Note: os.environ.get() is used directly here (NOT shared/config.py) because
    # Alembic migrations run in a separate process context where Pydantic Settings
    # cannot be safely bootstrapped. This is the documented exception in the design
    # for migration scripts.
    bind = op.get_bind()
    count = bind.execute(sa.text("SELECT COUNT(*) FROM admin_users")).scalar()

    if count == 0:
        admin_username = os.environ.get("ADMIN_USERNAME", "")
        admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")

        if not admin_username or not admin_password_hash:
            raise RuntimeError(
                "admin_users seed required but ADMIN_USERNAME / ADMIN_PASSWORD_HASH "
                "env vars are missing. Set them before running this migration.\n"
                "Generate hash with: python -c \"import bcrypt; "
                "print(bcrypt.hashpw(b'your_password', bcrypt.gensalt(rounds=12)).decode())\""
            )

        bind.execute(
            sa.text(
                "INSERT INTO admin_users "
                "(id, username, password_hash, role, is_active, created_at, updated_at) "
                "VALUES (:id, :username, :password_hash, 'admin', TRUE, now(), now())"
            ),
            {
                "id": str(uuid4()),
                "username": admin_username,
                "password_hash": admin_password_hash,
            },
        )
    # else: count >= 1 → skip seed (idempotent, FR-DB-4 / NFR-5)


def downgrade() -> None:
    # Reverse order: drop FK + index from escalations first, then drop admin_users

    # 1. Drop escalations FK artifacts
    op.drop_index("ix_escalations_resolved_by", table_name="escalations")
    op.drop_constraint(
        "fk_escalations_resolved_by_user",
        "escalations",
        type_="foreignkey",
    )
    op.drop_column("escalations", "resolved_by_user_id")

    # 2. Drop admin_users indexes then the table
    op.drop_index("ix_admin_users_role_active", table_name="admin_users")
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_table("admin_users")
