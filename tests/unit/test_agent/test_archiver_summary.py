"""T7 — Archiver reads conversation_summary from state and writes to ConversationHistory.summary.

Verifies that upsert_conversation_to_db correctly propagates conversation_summary
from AgentState into ConversationHistory.summary without requiring a live DB.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_state(
    conversation_id: str = "conv-1",
    messages: list | None = None,
    conversation_summary: str | None = None,
) -> dict:
    """Build a minimal archiver-compatible state dict."""
    return {
        "conversation_id": conversation_id,
        "customer_id": None,
        "messages": messages or [{"role": "human", "content": "Hola", "timestamp": None}],
        "conversation_summary": conversation_summary,
    }


def _make_session_with_parent(existing_parent=None):
    """Return an AsyncSession mock that simulates get-or-create for ConversationHistory."""
    session = MagicMock()

    # scalar_one_or_none() returns existing parent (or None → will create new)
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=existing_parent)
    scalar_result_count = MagicMock()
    scalar_result_count.scalar = MagicMock(return_value=0)

    async def _execute(stmt):
        # First call → select ConversationHistory
        # Second call → select ConversationMessage fingerprints
        # Third call → count
        _execute._call_count = getattr(_execute, "_call_count", 0) + 1
        if _execute._call_count == 1:
            return scalar_result
        if _execute._call_count == 2:
            fp_result = MagicMock()
            fp_result.all = MagicMock(return_value=[])
            return fp_result
        # count
        return scalar_result_count

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    return session


# ---------------------------------------------------------------------------
# T7a: summary propagated to parent.summary when present in state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archiver_writes_summary_to_conversation_history():
    """upsert_conversation_to_db sets parent.summary from state['conversation_summary']."""
    from agent.workers.conversation_archiver import upsert_conversation_to_db

    # Parent does NOT exist yet (will be created)
    session = _make_session_with_parent(existing_parent=None)
    state = _build_state(conversation_summary="RESUMEN_X")

    # Capture the ConversationHistory instance passed to session.add()
    created_parent = None

    def _capture_add(obj):
        nonlocal created_parent
        # The first add() call receives the ConversationHistory parent
        from database.models import ConversationHistory

        if isinstance(obj, ConversationHistory):
            created_parent = obj

    session.add = MagicMock(side_effect=_capture_add)

    await upsert_conversation_to_db(session, state)

    assert created_parent is not None, "ConversationHistory parent was never added to session"
    assert created_parent.summary == "RESUMEN_X"


# ---------------------------------------------------------------------------
# T7b: summary NOT written when key absent from state (graceful handling)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archiver_summary_absent_when_not_in_state():
    """upsert_conversation_to_db leaves parent.summary as None when conversation_summary absent."""
    from agent.workers.conversation_archiver import upsert_conversation_to_db

    session = _make_session_with_parent(existing_parent=None)
    state = _build_state(conversation_summary=None)

    created_parent = None

    def _capture_add(obj):
        nonlocal created_parent
        from database.models import ConversationHistory

        if isinstance(obj, ConversationHistory):
            created_parent = obj

    session.add = MagicMock(side_effect=_capture_add)

    await upsert_conversation_to_db(session, state)

    assert created_parent is not None
    # summary must remain None — archiver must not overwrite with empty value
    assert created_parent.summary is None
