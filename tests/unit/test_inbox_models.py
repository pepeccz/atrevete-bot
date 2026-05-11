"""Unit tests for inbox-related ORM model changes.

Verifies that:
  - ConversationMessage.author_user_id column exists and is nullable.
  - ConversationMessage has an 'author' relationship to AdminUser.
  - ConversationMessageRole enum contains the 'human_agent' value.
  - ConversationHistory has paused_at, resumed_at, context_injected_at nullable columns.
  - ORM-level instantiation works correctly (no DB required).

These tests inspect ORM metadata directly; no database connection is needed.
Integration-level tests (actual FK constraints) are deferred to PR-2.

Traces: FR-DB-1, FR-DB-2, FR-DB-3.
"""

from __future__ import annotations

from datetime import UTC
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect

from database.models import (
    AdminUser,
    ConversationHistory,
    ConversationMessage,
    ConversationMessageRole,
)

# ---------------------------------------------------------------------------
# ConversationMessageRole enum
# ---------------------------------------------------------------------------


class TestConversationMessageRole:
    """Tests for the new ConversationMessageRole enum (FR-DB-1)."""

    def test_has_human_agent_value(self):
        """ConversationMessageRole includes 'human_agent' (FR-DB-1)."""
        assert ConversationMessageRole.HUMAN_AGENT == "human_agent"

    def test_preserves_existing_values(self):
        """Existing role values (user, assistant, system) are preserved."""
        assert ConversationMessageRole.USER == "user"
        assert ConversationMessageRole.ASSISTANT == "assistant"
        assert ConversationMessageRole.SYSTEM == "system"

    def test_is_string_enum(self):
        """ConversationMessageRole is a str enum (compatible with DB string column)."""
        assert isinstance(ConversationMessageRole.HUMAN_AGENT, str)
        assert isinstance(ConversationMessageRole.USER, str)

    def test_all_four_values_present(self):
        """All four role values are defined."""
        values = {r.value for r in ConversationMessageRole}
        assert values == {"user", "assistant", "system", "human_agent"}

    def test_human_agent_fits_column_length(self):
        """'human_agent' (12 chars) fits within String(20) column limit."""
        assert len(ConversationMessageRole.HUMAN_AGENT.value) <= 20


# ---------------------------------------------------------------------------
# ConversationMessage — author_user_id column
# ---------------------------------------------------------------------------


class TestConversationMessageAuthorColumn:
    """Tests for ConversationMessage.author_user_id column (FR-DB-2)."""

    def test_author_user_id_column_exists(self):
        """ConversationMessage has an author_user_id column."""
        col_names = {col.key for col in sa_inspect(ConversationMessage).columns}
        assert "author_user_id" in col_names

    def test_author_user_id_is_nullable(self):
        """author_user_id is nullable (existing rows are unaffected by migration)."""
        col = sa_inspect(ConversationMessage).columns["author_user_id"]
        assert col.nullable is True

    def test_author_user_id_has_index(self):
        """author_user_id column has an index for efficient lookup."""
        col = ConversationMessage.__table__.c["author_user_id"]
        assert col.index is True

    def test_author_user_id_accepts_uuid_in_orm(self):
        """author_user_id can be set to a UUID value without error (ORM-level)."""
        user_id = uuid4()
        msg = ConversationMessage(
            conversation_history_id=uuid4(),
            role=ConversationMessageRole.HUMAN_AGENT.value,
            content="Hola, ¿en qué le puedo ayudar?",
            author_user_id=user_id,
        )
        assert msg.author_user_id == user_id

    def test_author_user_id_defaults_to_none(self):
        """author_user_id defaults to None for non-human_agent messages."""
        msg = ConversationMessage(
            conversation_history_id=uuid4(),
            role=ConversationMessageRole.USER.value,
            content="Hola",
        )
        assert msg.author_user_id is None

    def test_human_agent_role_validates_via_enum(self):
        """'human_agent' is a valid role string when validated via the enum."""
        valid_role = ConversationMessageRole.HUMAN_AGENT.value
        msg = ConversationMessage(
            conversation_history_id=uuid4(),
            role=valid_role,
            content="Test message from admin",
            author_user_id=uuid4(),
        )
        assert msg.role == "human_agent"

    def test_author_relationship_defined(self):
        """ConversationMessage has an 'author' relationship to AdminUser."""
        mapper = sa_inspect(ConversationMessage)
        relationship_names = {rel.key for rel in mapper.relationships}
        assert "author" in relationship_names

    def test_author_relationship_targets_admin_user(self):
        """The 'author' relationship points to AdminUser."""
        mapper = sa_inspect(ConversationMessage)
        author_rel = next(r for r in mapper.relationships if r.key == "author")
        assert author_rel.mapper.class_ is AdminUser


# ---------------------------------------------------------------------------
# ConversationHistory — pause/resume timestamps
# ---------------------------------------------------------------------------


class TestConversationHistoryTimestamps:
    """Tests for ConversationHistory pause/resume timestamp columns (FR-DB-3)."""

    def test_paused_at_column_exists(self):
        """ConversationHistory has a paused_at column."""
        col_names = {col.key for col in sa_inspect(ConversationHistory).columns}
        assert "paused_at" in col_names

    def test_resumed_at_column_exists(self):
        """ConversationHistory has a resumed_at column."""
        col_names = {col.key for col in sa_inspect(ConversationHistory).columns}
        assert "resumed_at" in col_names

    def test_context_injected_at_column_exists(self):
        """ConversationHistory has a context_injected_at column."""
        col_names = {col.key for col in sa_inspect(ConversationHistory).columns}
        assert "context_injected_at" in col_names

    def test_paused_at_is_nullable(self):
        """paused_at is nullable (existing rows require no backfill)."""
        col = sa_inspect(ConversationHistory).columns["paused_at"]
        assert col.nullable is True

    def test_resumed_at_is_nullable(self):
        """resumed_at is nullable."""
        col = sa_inspect(ConversationHistory).columns["resumed_at"]
        assert col.nullable is True

    def test_context_injected_at_is_nullable(self):
        """context_injected_at is nullable."""
        col = sa_inspect(ConversationHistory).columns["context_injected_at"]
        assert col.nullable is True

    def test_timestamps_default_to_none_in_orm(self):
        """All three timestamp columns default to None when not explicitly set."""
        history = ConversationHistory(
            conversation_id="test-conv-123",
        )
        assert history.paused_at is None
        assert history.resumed_at is None
        assert history.context_injected_at is None

    def test_paused_at_accepts_datetime(self):
        """paused_at can be assigned a datetime value at ORM level."""
        from datetime import datetime

        now = datetime.now(tz=UTC)
        history = ConversationHistory(
            conversation_id="test-conv-456",
            paused_at=now,
        )
        assert history.paused_at == now

    def test_all_three_timestamps_timezone_aware_columns(self):
        """All three columns use TIMESTAMP(timezone=True) / TIMESTAMPTZ."""

        for col_name in ("paused_at", "resumed_at", "context_injected_at"):
            col = ConversationHistory.__table__.c[col_name]
            # The column type should be a timezone-aware TIMESTAMP
            assert (
                col.type.timezone is True
            ), f"{col_name} must use DateTime(timezone=True) per NFR-7"
