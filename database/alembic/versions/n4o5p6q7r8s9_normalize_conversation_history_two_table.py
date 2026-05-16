"""Normalize conversation_history to two-table schema.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-03-10

Transforms `conversation_history` from a flat single-table design
(1 row per message) into a two-table parent/child schema:

  conversation_history     — 1 row per conversation (parent / metadata)
  conversation_messages    — 1 row per message (child, CASCADE-deleted with parent)

Changes applied:
  1. Create `conversation_messages` child table
  2. Migrate existing flat rows:
       - GROUP BY conversation_id → INSERT parent rows (with MIN/MAX timestamps,
         COUNT, and customer_id from the first row)
       - For each batch of conversation_ids → INSERT child rows
  3. Drop per-message columns from `conversation_history`
     (message_role, message_content, timestamp)
  4. Add parent-level columns to `conversation_history`
     (started_at, ended_at, message_count, summary, created_at)
  5. Add UNIQUE constraint on `conversation_history.conversation_id`
  6. Replace old composite index with new simpler index

Downgrade reverses all of the above: reconstructs flat rows from
child messages, drops the child table, and restores the old columns.

Data-migration batch size: 500 conversation_ids per iteration.
"""
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------

revision: str = "n4o5p6q7r8s9"
down_revision: str | None = "m3n4o5p6q7r8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # STEP 1 — Create `conversation_messages` child table
    # ------------------------------------------------------------------
    op.create_table(
        "conversation_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "conversation_history_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_history.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("chatwoot_message_id", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_index(
        "idx_conversation_messages_conv_created",
        "conversation_messages",
        ["conversation_history_id", "created_at"],
    )
    op.create_index(
        "ix_conv_messages_chatwoot_id",
        "conversation_messages",
        ["chatwoot_message_id"],
        postgresql_where=sa.text("chatwoot_message_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # STEP 2 — Add parent-level columns to conversation_history
    #           (nullable first so existing rows don't fail)
    # ------------------------------------------------------------------
    op.add_column(
        "conversation_history",
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "conversation_history",
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "conversation_history",
        sa.Column("message_count", sa.Integer, server_default="0", nullable=False),
    )
    op.add_column(
        "conversation_history",
        sa.Column("summary", sa.Text, nullable=True),
    )
    op.add_column(
        "conversation_history",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,  # nullable during migration; set below
        ),
    )

    # ------------------------------------------------------------------
    # STEP 3 — Data migration: flat rows → two-table
    #
    # Strategy:
    #   a) Collect DISTINCT conversation_ids in batches
    #   b) For each batch:
    #      - DELETE duplicate parent rows keeping only one representative
    #        (the flat table may already have one row per message, so we
    #         find the first row per conversation_id and use it as parent)
    #      - INSERT new child rows into conversation_messages
    #      - UPDATE the surviving parent row with aggregate metadata
    #   c) After all batches, delete the now-redundant additional parent
    #      rows that came from the original flat design
    #
    # Implementation note: we operate directly on the existing rows.
    # Each flat row IS already a row in conversation_history with a UUID id.
    # We pick ONE row per conversation_id to "promote" to the parent record
    # and then insert all messages (including the promoted row's content)
    # as children, then strip the per-message columns from the parent.
    # ------------------------------------------------------------------

    # 3a. Get all distinct conversation_ids
    result = conn.execute(
        sa.text("SELECT DISTINCT conversation_id FROM conversation_history ORDER BY conversation_id")
    )
    all_conv_ids = [row[0] for row in result]

    for batch_start in range(0, len(all_conv_ids), BATCH_SIZE):
        batch = all_conv_ids[batch_start : batch_start + BATCH_SIZE]

        # 3b. For each conversation_id in batch:
        #     - Find all flat rows (ordered by timestamp)
        #     - Pick the one with the lowest timestamp as the "parent" row
        #     - Insert all rows as ConversationMessage children
        #     - Delete all OTHER flat rows for this conversation
        #     - Update the surviving parent row with aggregated metadata
        for conv_id in batch:
            # Fetch all flat rows for this conversation, ordered chronologically
            rows = conn.execute(
                sa.text(
                    """
                    SELECT id, customer_id, timestamp, message_role, message_content
                    FROM conversation_history
                    WHERE conversation_id = :conv_id
                    ORDER BY timestamp ASC NULLS LAST, id ASC
                    """
                ),
                {"conv_id": conv_id},
            ).fetchall()

            if not rows:
                continue

            # The first row becomes the parent record (we keep its UUID)
            parent_row = rows[0]
            parent_id = parent_row[0]
            parent_customer_id = parent_row[1]
            started_at = parent_row[2]  # earliest timestamp
            ended_at = rows[-1][2]       # latest timestamp
            message_count = len(rows)

            # Find customer_id: use the first non-null value
            customer_id = None
            for row in rows:
                if row[1] is not None:
                    customer_id = row[1]
                    break

            # 3c. Insert all messages as children
            for row in rows:
                row_id, _cust, ts, role_val, content_val = row
                # Map MessageRole enum value / name to plain string
                # In the old schema, role is stored as 'user'/'assistant'/'system'
                role_str = str(role_val).lower() if role_val else "user"
                # Handle both enum value format and SQLEnum name format
                # e.g. MessageRole.USER → 'user', or just 'user'
                if "." in role_str:
                    role_str = role_str.split(".")[-1].lower()

                child_id = str(uuid4())
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO conversation_messages
                            (id, conversation_history_id, role, content, created_at)
                        VALUES
                            (:id, :conv_hist_id, :role, :content, :created_at)
                        """
                    ),
                    {
                        "id": child_id,
                        "conv_hist_id": str(parent_id),
                        "role": role_str,
                        "content": content_val or "",
                        "created_at": ts or sa.text("NOW()"),
                    },
                )

            # 3d. Delete all other (non-parent) flat rows for this conversation
            other_ids = [str(row[0]) for row in rows[1:]]
            if other_ids:
                conn.execute(
                    sa.text(
                        "DELETE FROM conversation_history WHERE id = ANY(:ids)"
                    ),
                    {"ids": other_ids},
                )

            # 3e. Update the surviving parent row with aggregated metadata
            conn.execute(
                sa.text(
                    """
                    UPDATE conversation_history
                    SET
                        customer_id   = :customer_id,
                        started_at    = :started_at,
                        ended_at      = :ended_at,
                        message_count = :message_count,
                        created_at    = COALESCE(started_at, NOW())
                    WHERE id = :parent_id
                    """
                ),
                {
                    "customer_id": str(customer_id) if customer_id else None,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "message_count": message_count,
                    "parent_id": str(parent_id),
                },
            )

    # ------------------------------------------------------------------
    # STEP 4 — Set created_at for any remaining NULL rows (edge case:
    #           empty conversation_history table or rows inserted after
    #           the migration started without started_at)
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE conversation_history SET created_at = NOW() WHERE created_at IS NULL"
        )
    )
    # Now make created_at non-nullable
    op.alter_column("conversation_history", "created_at", nullable=False)

    # ------------------------------------------------------------------
    # STEP 5 — Drop per-message columns from conversation_history
    # ------------------------------------------------------------------
    op.drop_column("conversation_history", "message_role")
    op.drop_column("conversation_history", "message_content")
    op.drop_column("conversation_history", "timestamp")

    # ------------------------------------------------------------------
    # STEP 6 — Add UNIQUE constraint on conversation_id and replace index
    # ------------------------------------------------------------------
    # Drop old indexes that referenced the dropped columns or are superseded
    op.drop_index(
        "idx_conversation_history_conversation_timestamp",
        table_name="conversation_history",
        if_exists=True,
    )
    op.drop_index(
        "idx_conversation_history_timestamp_desc",
        table_name="conversation_history",
        if_exists=True,
    )

    # Add unique constraint (conversation_id is now a true PK-like field)
    op.create_unique_constraint(
        "uq_conversation_history_conversation_id",
        "conversation_history",
        ["conversation_id"],
    )

    # New composite index for archiver / admin panel queries
    op.create_index(
        "idx_conversation_history_conversation_started",
        "conversation_history",
        ["conversation_id", "started_at"],
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # STEP 1 — Restore per-message columns on conversation_history
    # ------------------------------------------------------------------
    op.add_column(
        "conversation_history",
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=True,  # nullable during restore; set below
        ),
    )
    op.add_column(
        "conversation_history",
        sa.Column(
            "message_role",
            sa.Enum("user", "assistant", "system", name="message_role", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "conversation_history",
        sa.Column("message_content", sa.Text, nullable=True),
    )

    # ------------------------------------------------------------------
    # STEP 2 — Reconstruct flat rows from conversation_messages
    #
    # For each parent conversation:
    #   - Update the existing parent row with the FIRST child's data
    #   - Insert NEW flat rows for each subsequent child message
    # ------------------------------------------------------------------
    result = conn.execute(
        sa.text("SELECT id, conversation_id, customer_id FROM conversation_history ORDER BY id")
    )
    parent_rows = result.fetchall()

    for parent_id, conv_id, customer_id in parent_rows:
        # Get all child messages in order
        children = conn.execute(
            sa.text(
                """
                SELECT role, content, created_at
                FROM conversation_messages
                WHERE conversation_history_id = :parent_id
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"parent_id": str(parent_id)},
        ).fetchall()

        if not children:
            # No messages — set sensible defaults on the parent
            conn.execute(
                sa.text(
                    """
                    UPDATE conversation_history
                    SET timestamp = NOW(),
                        message_role = 'user',
                        message_content = ''
                    WHERE id = :parent_id
                    """
                ),
                {"parent_id": str(parent_id)},
            )
            continue

        # Update parent row with the FIRST child's data
        first = children[0]
        conn.execute(
            sa.text(
                """
                UPDATE conversation_history
                SET timestamp = :ts,
                    message_role = :role,
                    message_content = :content
                WHERE id = :parent_id
                """
            ),
            {
                "ts": first[2],
                "role": first[0],
                "content": first[1],
                "parent_id": str(parent_id),
            },
        )

        # Insert flat rows for each subsequent child message
        for child_role, child_content, child_ts in children[1:]:
            new_id = str(uuid4())
            conn.execute(
                sa.text(
                    """
                    INSERT INTO conversation_history
                        (id, customer_id, conversation_id, timestamp, message_role, message_content, metadata)
                    VALUES
                        (:id, :customer_id, :conv_id, :ts, :role, :content, '{}'::jsonb)
                    """
                ),
                {
                    "id": new_id,
                    "customer_id": str(customer_id) if customer_id else None,
                    "conv_id": conv_id,
                    "ts": child_ts,
                    "role": child_role,
                    "content": child_content,
                },
            )

    # ------------------------------------------------------------------
    # STEP 3 — Make per-message columns non-nullable
    # ------------------------------------------------------------------
    # Set any remaining NULLs before making non-nullable
    conn.execute(
        sa.text(
            """
            UPDATE conversation_history
            SET timestamp = NOW()
            WHERE timestamp IS NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE conversation_history
            SET message_role = 'user'
            WHERE message_role IS NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE conversation_history
            SET message_content = ''
            WHERE message_content IS NULL
            """
        )
    )
    op.alter_column("conversation_history", "timestamp", nullable=False)
    op.alter_column("conversation_history", "message_role", nullable=False)
    op.alter_column("conversation_history", "message_content", nullable=False)

    # ------------------------------------------------------------------
    # STEP 4 — Remove new indexes and constraint on conversation_history
    # ------------------------------------------------------------------
    op.drop_index("idx_conversation_history_conversation_started", table_name="conversation_history", if_exists=True)
    op.drop_constraint("uq_conversation_history_conversation_id", "conversation_history", type_="unique")

    # Restore old indexes
    op.create_index(
        "idx_conversation_history_conversation_timestamp",
        "conversation_history",
        ["conversation_id", "timestamp"],
    )
    op.create_index(
        "idx_conversation_history_timestamp_desc",
        "conversation_history",
        ["timestamp"],
        postgresql_ops={"timestamp": "DESC"},
    )

    # ------------------------------------------------------------------
    # STEP 5 — Drop new parent-level columns from conversation_history
    # ------------------------------------------------------------------
    op.drop_column("conversation_history", "started_at")
    op.drop_column("conversation_history", "ended_at")
    op.drop_column("conversation_history", "message_count")
    op.drop_column("conversation_history", "summary")
    op.drop_column("conversation_history", "created_at")

    # ------------------------------------------------------------------
    # STEP 6 — Drop conversation_messages table
    # ------------------------------------------------------------------
    op.drop_index("ix_conv_messages_chatwoot_id", table_name="conversation_messages", if_exists=True)
    op.drop_index("idx_conversation_messages_conv_created", table_name="conversation_messages", if_exists=True)
    op.drop_table("conversation_messages")
