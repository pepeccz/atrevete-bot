"""
Unit tests for conversation_notes_service.py — PR-2.

Tests authorization rules and validation logic using mocked ORM objects.
No real DB connection required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from api.services.conversation_notes_service import (
    _make_dto,
    create_note,
    delete_note,
    update_note,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_note(
    author_user_id=None,
    content="Test note",
    author_display_name=None,
    author_username="admin",
):
    note = MagicMock()
    note.id = uuid4()
    note.conversation_history_id = uuid4()
    note.author_user_id = author_user_id or uuid4()
    note.content = content
    note.created_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00+00:00"))
    note.updated_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00+00:00"))

    if author_display_name:
        note.author = MagicMock(display_name=author_display_name, username=author_username)
    else:
        note.author = MagicMock(display_name=None, username=author_username)
    return note


# ─── _make_dto ────────────────────────────────────────────────────────────────


def test_make_dto_with_author_display_name():
    note = _make_note(author_display_name="María García")
    dto = _make_dto(note)
    assert dto["author_name"] == "María García"
    assert dto["content"] == "Test note"


def test_make_dto_falls_back_to_username():
    note = _make_note(author_username="operadora1")
    dto = _make_dto(note)
    assert dto["author_name"] == "operadora1"


def test_make_dto_deleted_author():
    note = _make_note()
    note.author = None
    note.author_user_id = None
    dto = _make_dto(note)
    assert dto["author_name"] == "Cuenta eliminada"
    assert dto["author_user_id"] is None


# ─── create_note ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_note_rejects_empty_content():
    session = AsyncMock()
    with pytest.raises(ValueError, match="vacío"):
        await create_note(uuid4(), uuid4(), "   ", session)


@pytest.mark.asyncio
async def test_create_note_raises_lookup_when_conversation_missing():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(LookupError, match="no encontrada"):
        await create_note(uuid4(), uuid4(), "Válido", session)


# ─── update_note ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_note_permission_error_for_other_author():
    author_id = uuid4()
    other_user_id = uuid4()

    note = _make_note(author_user_id=author_id)

    with patch(
        "api.services.conversation_notes_service.get_note", AsyncMock(return_value=note)
    ):
        session = AsyncMock()
        with pytest.raises(PermissionError, match="Solo el autor"):
            await update_note(note.id, "Nuevo contenido", other_user_id, session)


@pytest.mark.asyncio
async def test_update_note_raises_lookup_when_missing():
    with patch(
        "api.services.conversation_notes_service.get_note", AsyncMock(return_value=None)
    ):
        session = AsyncMock()
        with pytest.raises(LookupError, match="no encontrada"):
            await update_note(uuid4(), "Contenido", uuid4(), session)


@pytest.mark.asyncio
async def test_update_note_rejects_empty_content():
    author_id = uuid4()
    note = _make_note(author_user_id=author_id)

    with patch(
        "api.services.conversation_notes_service.get_note", AsyncMock(return_value=note)
    ):
        session = AsyncMock()
        with pytest.raises(ValueError, match="vacío"):
            await update_note(note.id, "   ", author_id, session)


# ─── delete_note ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_note_raises_lookup_when_missing():
    with patch(
        "api.services.conversation_notes_service.get_note", AsyncMock(return_value=None)
    ):
        session = AsyncMock()
        with pytest.raises(LookupError, match="no encontrada"):
            await delete_note(uuid4(), uuid4(), False, session)


@pytest.mark.asyncio
async def test_delete_note_permission_error_for_non_author_non_admin():
    author_id = uuid4()
    other_user_id = uuid4()
    note = _make_note(author_user_id=author_id)

    with patch(
        "api.services.conversation_notes_service.get_note", AsyncMock(return_value=note)
    ):
        session = AsyncMock()
        with pytest.raises(PermissionError, match="permiso"):
            await delete_note(note.id, other_user_id, is_admin=False, session=session)


@pytest.mark.asyncio
async def test_delete_note_admin_can_delete_any_note():
    """Admin role can delete notes they did not author."""
    author_id = uuid4()
    admin_id = uuid4()
    note = _make_note(author_user_id=author_id)

    async def _mock_delete(obj):
        pass

    with patch(
        "api.services.conversation_notes_service.get_note", AsyncMock(return_value=note)
    ):
        session = AsyncMock()
        session.delete = AsyncMock()
        result = await delete_note(note.id, admin_id, is_admin=True, session=session)
        assert result is True
        session.delete.assert_called_once_with(note)


@pytest.mark.asyncio
async def test_delete_note_author_can_delete_own_note():
    author_id = uuid4()
    note = _make_note(author_user_id=author_id)

    with patch(
        "api.services.conversation_notes_service.get_note", AsyncMock(return_value=note)
    ):
        session = AsyncMock()
        session.delete = AsyncMock()
        result = await delete_note(note.id, author_id, is_admin=False, session=session)
        assert result is True
