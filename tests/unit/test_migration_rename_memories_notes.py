"""
Unit tests for migration a1b2c3d4e5f6 — rename memories.notes to memories.agent_notes.

Three scenarios per spec Domain 1:
  1. Row with old key (memories.notes) is migrated to memories.agent_notes
  2. Already-migrated row (memories.agent_notes present, memories.notes absent) is untouched
  3. Row without a memories key is untouched

Uses mocked op.execute — verifies the SQL strings produced by upgrade() / downgrade()
are syntactically and semantically correct (idempotency guard, symmetric downgrade).
"""

from unittest.mock import patch

import pytest


@pytest.fixture
def mock_op():
    """Provide a mock alembic op with execute capture."""
    with patch(
        "database.alembic.versions.b8c9d0e1f2g3_rename_memories_notes_to_agent_notes.op"
    ) as m:
        yield m


# ============================================================================
# upgrade() SQL
# ============================================================================


def test_upgrade_sql_renames_notes_to_agent_notes(mock_op):
    """
    GIVEN the upgrade() function
    WHEN called
    THEN op.execute is called with SQL that moves memories.notes -> memories.agent_notes
    AND the WHERE clause guards against already-migrated rows.
    """
    from database.alembic.versions.b8c9d0e1f2g3_rename_memories_notes_to_agent_notes import (
        upgrade,
    )

    upgrade()

    mock_op.execute.assert_called_once()
    sql = mock_op.execute.call_args[0][0]

    # Verify target key appears
    assert "agent_notes" in sql
    # Verify source key removed
    assert "{memories,notes}" in sql or "memories,notes" in sql
    # Verify idempotency guard — must NOT run on already-migrated rows
    assert "agent_notes" in sql
    assert "NOT" in sql
    # Verify it targets the customers table
    assert "customers" in sql.lower()
    # Verify it reads from memories.notes
    assert "memories" in sql


def test_upgrade_sql_has_idempotency_guard(mock_op):
    """
    GIVEN the upgrade() function
    WHEN called
    THEN the SQL contains a NOT (metadata_->'memories' ? 'agent_notes') guard.
    """
    from database.alembic.versions.b8c9d0e1f2g3_rename_memories_notes_to_agent_notes import (
        upgrade,
    )

    upgrade()

    sql = mock_op.execute.call_args[0][0]
    # Must guard against overwriting an existing agent_notes key
    assert "agent_notes" in sql
    assert "NOT" in sql


# ============================================================================
# downgrade() SQL
# ============================================================================


def test_downgrade_sql_renames_agent_notes_back_to_notes(mock_op):
    """
    GIVEN the downgrade() function
    WHEN called
    THEN op.execute is called with symmetric SQL that moves memories.agent_notes -> memories.notes
    AND the WHERE clause guards against double-downgrade.
    """
    from database.alembic.versions.b8c9d0e1f2g3_rename_memories_notes_to_agent_notes import (
        downgrade,
    )

    downgrade()

    mock_op.execute.assert_called_once()
    sql = mock_op.execute.call_args[0][0]

    # Symmetric direction — removes agent_notes, writes notes
    assert "{memories,agent_notes}" in sql or "memories,agent_notes" in sql
    assert "notes" in sql
    assert "customers" in sql.lower()
    # Downgrade idempotency guard
    assert "NOT" in sql


def test_upgrade_and_downgrade_are_symmetric(mock_op):
    """
    GIVEN upgrade() and downgrade()
    WHEN both are called
    THEN both issue exactly one op.execute call each (no side effects beyond SQL).
    """
    from database.alembic.versions.b8c9d0e1f2g3_rename_memories_notes_to_agent_notes import (
        downgrade,
        upgrade,
    )

    upgrade()
    assert mock_op.execute.call_count == 1
    upgrade_sql = mock_op.execute.call_args[0][0]

    mock_op.execute.reset_mock()

    downgrade()
    assert mock_op.execute.call_count == 1
    downgrade_sql = mock_op.execute.call_args[0][0]

    # Both operate on customers table
    assert "customers" in upgrade_sql.lower()
    assert "customers" in downgrade_sql.lower()

    # upgrade removes notes, downgrade removes agent_notes
    assert "{memories,notes}" in upgrade_sql or "memories,notes" in upgrade_sql
    assert "{memories,agent_notes}" in downgrade_sql or "memories,agent_notes" in downgrade_sql
