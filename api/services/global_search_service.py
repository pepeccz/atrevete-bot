"""
Global conversation search service.

Searches conversations by customer name, customer phone, or message content
using PostgreSQL ILIKE queries accelerated by the ``pg_trgm`` GIN indexes
added in the PR-2 migration.

Design (ADR-D6):
- ILIKE '%q%' against ``customers.name``, ``customers.phone``, and
  ``conversation_messages.content``.
- Server-side sanitization: ``%``, ``_``, ``\\`` in the query are escaped so
  they are treated as literals, not ILIKE wildcards.
- Empty or whitespace-only queries return an empty list immediately.
- Results de-duplicated by conversation_history.id, ordered by most-recent
  message activity (``max(conversation_messages.created_at) DESC``).
- Hard limit capped at the caller-supplied ``limit`` (default 50).
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import ConversationHistory, ConversationMessage, Customer

logger = logging.getLogger(__name__)


# ─── Input sanitisation ───────────────────────────────────────────────────────


def _sanitize_query(q: str) -> str | None:
    """Escape ILIKE special characters and return None for empty input.

    Escapes ``\\``, ``%``, and ``_`` so they are treated as literals.
    Returns ``None`` when the cleaned query is empty or whitespace-only,
    signalling the caller to skip the DB query.
    """
    q = q.strip()
    if not q:
        return None
    # Order matters: escape backslash first to avoid double-escaping
    q = q.replace("\\", "\\\\")
    q = q.replace("%", "\\%")
    q = q.replace("_", "\\_")
    return q


# ─── Service function ─────────────────────────────────────────────────────────


async def search_conversations(
    q: str,
    session: AsyncSession,
    limit: int = 50,
) -> list[dict]:
    """Search conversations by customer name, phone, or message content.

    Args:
        q: Raw search term from the user (unsanitized).
        session: Active async SQLAlchemy session (read-only).
        limit: Maximum number of conversations to return (default 50).

    Returns:
        List of conversation dicts matching the shape of list_conversations
        items (same as ``_resolve_conversation_list_item``).  Empty list when
        ``q`` is blank or no matches found.
    """
    safe_q = _sanitize_query(q)
    if safe_q is None:
        return []

    pattern = f"%{safe_q}%"

    t_start = time.monotonic()

    # ── Subquery: conversations matched by customer first_name or phone ───
    customer_match_sq = (
        select(ConversationHistory.id)
        .join(Customer, Customer.id == ConversationHistory.customer_id, isouter=True)
        .where(
            or_(
                Customer.first_name.ilike(pattern),
                Customer.phone.ilike(pattern),
            )
        )
    )

    # ── Subquery: conversations matched by message content ─────────────────
    message_match_sq = (
        select(ConversationMessage.conversation_history_id)
        .where(ConversationMessage.content.ilike(pattern))
        .distinct()
    )

    # ── Combined: conversations matched by either criteria ─────────────────
    # We compute max(message.created_at) for ordering and select distinct
    # conversation rows in a single pass.
    max_msg_created_at = (
        select(func.max(ConversationMessage.created_at))
        .where(ConversationMessage.conversation_history_id == ConversationHistory.id)
        .correlate(ConversationHistory)
        .scalar_subquery()
    )

    stmt = (
        select(ConversationHistory, max_msg_created_at.label("last_activity"))
        .options(selectinload(ConversationHistory.customer))
        .where(
            or_(
                ConversationHistory.id.in_(customer_match_sq),
                ConversationHistory.id.in_(message_match_sq),
            )
        )
        .order_by(max_msg_created_at.desc().nullslast())
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

    elapsed_ms = (time.monotonic() - t_start) * 1000
    logger.info(
        "global_search q=%r returned %d results in %.1fms",
        safe_q,
        len(rows),
        elapsed_ms,
    )

    items = []
    for row in rows:
        conv: ConversationHistory = row[0]
        items.append(_to_list_item(conv))

    return items


def _to_list_item(conv: ConversationHistory) -> dict:
    """Serialize a ConversationHistory to the list-item dict shape."""
    customer = conv.customer
    customer_name: str | None = None
    if customer is not None:
        customer_name = f"{customer.first_name} {customer.last_name or ''}".strip() or None

    return {
        "id": str(conv.id),
        "conversation_id": conv.conversation_id,
        "customer_id": str(conv.customer_id) if conv.customer_id else None,
        "customer_name": customer_name,
        "started_at": conv.started_at.isoformat() if conv.started_at else None,
        "ended_at": conv.ended_at.isoformat() if conv.ended_at else None,
        "message_count": conv.message_count,
        "summary": conv.summary,
        "paused_at": conv.paused_at.isoformat() if conv.paused_at else None,
        "resumed_at": conv.resumed_at.isoformat() if conv.resumed_at else None,
        "created_at": conv.created_at.isoformat(),
        "source": "db",
    }
