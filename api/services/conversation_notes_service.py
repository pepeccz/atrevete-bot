"""
Conversation notes service — CRUD operations for operator notes.

Notes are created by authenticated admin/stylist users (AdminUser) and
attached to a specific ConversationHistory row.  Authorization rules:

- ``create_note``: any authenticated user may create a note.
- ``update_note``: only the original author may update (raises PermissionError
  when called by a different user, regardless of role).
- ``delete_note``: the original author OR any user with ``is_admin=True``
  may delete.

All methods accept an open ``AsyncSession`` and commit internally.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ConversationHistory, ConversationNote

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ─── DTO ──────────────────────────────────────────────────────────────────────

# ConversationNoteDTO lives in api/models/inbox.py so it can be reused by both
# the route layer and this service.  Import lazily to avoid circular imports.


def _make_dto(note: ConversationNote) -> dict:
    """Map an ORM ConversationNote to a plain dict (serialised by the route)."""
    author_name: str
    if note.author is not None:
        author_name = note.author.display_name or note.author.username
    else:
        author_name = "Cuenta eliminada"

    return {
        "id": str(note.id),
        "content": note.content,
        "author_user_id": str(note.author_user_id) if note.author_user_id else None,
        "author_name": author_name,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


# ─── Service functions ────────────────────────────────────────────────────────


async def create_note(
    conversation_id: UUID,
    author_user_id: UUID,
    content: str,
    session: AsyncSession,
) -> dict:
    """Create a new operator note for a conversation.

    Args:
        conversation_id: ConversationHistory.id (UUID primary key).
        author_user_id: AdminUser.id of the note author.
        content: Note body — will be stripped of leading/trailing whitespace.
        session: Active async SQLAlchemy session.

    Returns:
        A dict matching ConversationNoteDTO shape.

    Raises:
        ValueError: when ``content`` is empty after stripping.
        LookupError: when the conversation does not exist.
    """
    content = content.strip()
    if not content:
        raise ValueError("El contenido de la nota no puede estar vacío.")

    # Verify parent conversation exists
    result = await session.execute(
        select(ConversationHistory).where(ConversationHistory.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise LookupError("Conversación no encontrada.")

    note = ConversationNote(
        conversation_history_id=conversation_id,
        author_user_id=author_user_id,
        content=content,
    )
    session.add(note)
    await session.flush()  # populate note.id + server defaults
    await session.refresh(note, attribute_names=["author"])
    await session.commit()

    logger.info("Note %s created for conversation %s", note.id, conversation_id)
    return _make_dto(note)


async def list_notes(
    conversation_id: UUID,
    session: AsyncSession,
) -> list[dict]:
    """List all notes for a conversation, ordered by ``created_at DESC``.

    Returns an empty list when the conversation has no notes (does NOT
    raise a 404 — callers should verify the conversation exists separately
    if needed).
    """
    result = await session.execute(
        select(ConversationNote)
        .where(ConversationNote.conversation_history_id == conversation_id)
        .order_by(ConversationNote.created_at.desc())
    )
    notes = list(result.scalars().all())
    return [_make_dto(n) for n in notes]


async def get_note(
    note_id: UUID,
    session: AsyncSession,
) -> ConversationNote | None:
    """Return a single ConversationNote by primary key, or None if not found."""
    result = await session.execute(
        select(ConversationNote).where(ConversationNote.id == note_id)
    )
    return result.scalar_one_or_none()


async def update_note(
    note_id: UUID,
    content: str,
    author_user_id: UUID,
    session: AsyncSession,
) -> dict:
    """Update the content of an existing note.

    Only the original author may update a note.

    Args:
        note_id: ConversationNote.id (UUID primary key).
        content: New note body — will be stripped.
        author_user_id: AdminUser.id of the requester.
        session: Active async SQLAlchemy session.

    Returns:
        Updated ConversationNoteDTO dict.

    Raises:
        LookupError: when the note does not exist.
        ValueError: when ``content`` is empty after stripping.
        PermissionError: when the requester is not the original author.
    """
    note = await get_note(note_id, session)
    if note is None:
        raise LookupError("Nota no encontrada.")

    content = content.strip()
    if not content:
        raise ValueError("El contenido de la nota no puede estar vacío.")

    if note.author_user_id != author_user_id:
        raise PermissionError("Solo el autor puede editar esta nota.")

    note.content = content
    note.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(note, attribute_names=["author"])
    await session.commit()

    return _make_dto(note)


async def delete_note(
    note_id: UUID,
    author_user_id: UUID,
    is_admin: bool,
    session: AsyncSession,
) -> bool:
    """Delete a note by ID.

    The original author OR any admin-role user may delete.

    Args:
        note_id: ConversationNote.id.
        author_user_id: AdminUser.id of the requester.
        is_admin: True when the requester has the ``admin`` role.
        session: Active async SQLAlchemy session.

    Returns:
        True on success.

    Raises:
        LookupError: when the note does not exist.
        PermissionError: when the requester is neither the author nor an admin.
    """
    note = await get_note(note_id, session)
    if note is None:
        raise LookupError("Nota no encontrada.")

    if not is_admin and note.author_user_id != author_user_id:
        raise PermissionError("No tienes permiso para eliminar esta nota.")

    await session.delete(note)
    await session.commit()
    return True
