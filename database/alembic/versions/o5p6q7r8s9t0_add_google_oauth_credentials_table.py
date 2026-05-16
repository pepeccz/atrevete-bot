"""add_google_oauth_credentials_table

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-03-11

Adds the `google_oauth_credentials` table to store encrypted OAuth2 tokens
obtained when the admin connects their Google account via the OAuth2 flow.

The table enforces a maximum of one active credential at a time via a partial
unique index: `uq_google_oauth_active` on `is_active` WHERE `is_active = true`.

Tokens are stored encrypted (Fernet symmetric encryption) — never in plaintext.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------

revision: str = "o5p6q7r8s9t0"
down_revision: str | None = "n4o5p6q7r8s9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # Create the google_oauth_credentials table
    op.create_table(
        "google_oauth_credentials",
        # Primary key — server-generated UUID
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Encrypted token fields (Fernet-encrypted, base64-encoded)
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        # Token expiry — nullable (some providers omit it)
        sa.Column(
            "token_expiry",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        # Google account info
        sa.Column("connected_email", sa.String(255), nullable=False),
        # OAuth2 scopes granted (list of scope strings)
        sa.Column(
            "calendar_scopes",
            postgresql.ARRAY(sa.String()),
            nullable=True,
        ),
        # Status
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # Connection tracking
        sa.Column(
            "connected_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_refresh_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        # Audit timestamps
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
            onupdate=sa.func.now(),
        ),
    )

    # Partial unique index: only ONE active credential at a time
    # This prevents inserting a second row with is_active=true without
    # first deactivating the current one.
    op.create_index(
        "uq_google_oauth_active",
        "google_oauth_credentials",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    # General index for history queries (admin panel — list all credentials by date)
    op.create_index(
        "idx_google_oauth_connected_at",
        "google_oauth_credentials",
        ["connected_at"],
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # Drop indexes first, then the table
    op.drop_index("idx_google_oauth_connected_at", table_name="google_oauth_credentials")
    op.drop_index(
        "uq_google_oauth_active",
        table_name="google_oauth_credentials",
        postgresql_where=sa.text("is_active = true"),
    )
    op.drop_table("google_oauth_credentials")
