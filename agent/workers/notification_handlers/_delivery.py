"""Shared conversation-threading delivery helper for proactive WhatsApp notifications.

Resolves each customer's canonical Chatwoot conversation (the latest
``ConversationHistory`` row for their ``customer_id``) and threads outbound worker
templates into it, instead of letting ``send_template_message`` spawn a brand-new
conversation per notification. Falls back to creating a new conversation — and
persisting it as canonical — when no history row exists yet, or when Chatwoot
rejects the resolved conversation id.

Co-located with the 3 notification handlers (confirm_48h, reminder_24h,
final_warning) that call ``deliver_template`` — mirrors the ``_retry.py`` sibling
module pattern. Does not touch the ``NotificationHandler`` contract in ``base.py``.

Design: sdd/context-coherence D1, D2, D3, D6 (obs #7495).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.connection import get_async_session
from database.models import ConversationHistory, ConversationMessage, ConversationMessageRole
from shared.chatwoot_client import ConversationSendOutcome

logger = logging.getLogger(__name__)


async def resolve_conversation(session: Any, customer_id: UUID) -> ConversationHistory | None:
    """Return the customer's canonical (latest) ConversationHistory row, or None.

    Canonical = latest row by started_at, tiebreak on created_at. Deliberately no
    ``ended_at`` or ``paused_at`` filter: ``ended_at`` is bumped on every inbound
    (last-activity marker, not a closed flag) and a paused conversation is still a
    valid target for a customer-facing proactive template (D1).
    """
    stmt = (
        select(ConversationHistory)
        .where(ConversationHistory.customer_id == customer_id)
        .order_by(ConversationHistory.started_at.desc(), ConversationHistory.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def _persist_sent_message(history_id: UUID, content: str) -> None:
    """Best-effort persistence of a worker-sent template as a ConversationMessage.

    Independent session/commit from the send itself and from ``mark_sent_fn`` — a
    failure here is logged and swallowed; the template was already delivered (D6).
    """
    try:
        async with get_async_session() as session:
            session.add(
                ConversationMessage(
                    conversation_history_id=history_id,
                    role=ConversationMessageRole.ASSISTANT.value,
                    content=content,
                    author_type="bot",
                    author_user_id=None,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
    except Exception:
        logger.warning(
            "Failed to persist worker-sent ConversationMessage for history_id=%s",
            history_id,
            exc_info=True,
        )


async def _create_fallback_history(customer_id: UUID, conversation_id: int) -> UUID | None:
    """Persist a minimal ConversationHistory row for a newly-created conversation.

    Makes the new conversation canonical immediately, preventing a second spurious
    fallback-create before the customer's next inbound webhook would otherwise do
    the same (self-healing note, D3). Returns the new row's id, or None on failure.

    Race guard (FIX 5, sdd/context-coherence): the webhook's ``upsert_conversation_history``
    can independently insert a row for this SAME ``conversation_id`` (e.g. the customer
    replies to the just-created Chatwoot conversation before this commit lands). On a
    unique-constraint IntegrityError, roll back and reuse the row that won the race
    instead of dropping this send's persistence entirely.
    """
    now = datetime.now(UTC)
    conversation_id_str = str(conversation_id)
    try:
        async with get_async_session() as session:
            history = ConversationHistory(
                conversation_id=conversation_id_str,
                customer_id=customer_id,
                started_at=now,
                ended_at=now,
                message_count=0,
                metadata_={},
            )
            session.add(history)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(ConversationHistory).where(
                        ConversationHistory.conversation_id == conversation_id_str
                    )
                )
                existing = result.scalars().first()
                if existing is None:
                    logger.warning(
                        "IntegrityError creating fallback ConversationHistory for "
                        "conversation_id=%s but re-select found no row — giving up",
                        conversation_id,
                    )
                    return None
                logger.info(
                    "Fallback ConversationHistory for conversation_id=%s was created by a "
                    "concurrent writer — reusing existing row %s",
                    conversation_id,
                    existing.id,
                )
                return existing.id
            await session.refresh(history)
            return history.id
    except Exception:
        logger.warning(
            "Failed to persist fallback ConversationHistory for new conversation_id=%s",
            conversation_id,
            exc_info=True,
        )
        return None


async def deliver_template(
    chatwoot: Any,
    appt: Any,
    template_name: str,
    body_params: dict[str, str],
    fallback_content: str,
    category: str = "UTILITY",
    language: str = "es",
) -> bool:
    """Send a WhatsApp template into the customer's canonical conversation.

    Flow: resolve the latest ConversationHistory row for ``appt.customer_id`` →
    if found, send with ``conversation_id=int(history.conversation_id)`` (D2) →
    on resolver-miss OR a definitive Chatwoot REJECTED outcome for that id, fall
    back to creating a new conversation (D3) and persist it as the new canonical
    history. A TRANSIENT outcome (network error, timeout, 5xx) does NOT fall
    back — it returns False so the worker's own backoff/retry (mark_failed_fn /
    next_retry_at) targets the SAME conversation on the next poll cycle instead
    of fragmenting the customer's history (sdd/context-coherence FIX 1). On any
    successful send, best-effort persists a ConversationMessage so the send is
    visible in ``conversation_messages`` (D6).
    """
    phone = getattr(appt.customer, "phone", None) if getattr(appt, "customer", None) else None
    if not phone:
        logger.warning("Appointment %s has no customer phone — cannot deliver template", appt.id)
        return False

    async with get_async_session() as session:
        history = await resolve_conversation(session, appt.customer_id)

    if history is not None:
        try:
            conversation_id_int = int(history.conversation_id)
        except (TypeError, ValueError):
            # FIX 7: a corrupt/non-numeric conversation_id must never raise —
            # log and treat this as a resolver-miss so the fallback-create path
            # below still gets a valid new conversation for the customer.
            logger.warning(
                "ConversationHistory %s has non-numeric conversation_id=%r for appt %s — "
                "treating as no-history and falling back to a new conversation",
                history.id,
                history.conversation_id,
                appt.id,
            )
            history = None
        else:
            outcome = await chatwoot.send_template_to_conversation_checked(
                conversation_id=conversation_id_int,
                customer_phone=phone,
                template_name=template_name,
                body_params=body_params,
                category=category,
                language=language,
                fallback_content=fallback_content,
            )
            if outcome is ConversationSendOutcome.SENT:
                await _persist_sent_message(history.id, fallback_content)
                return True
            if outcome is ConversationSendOutcome.TRANSIENT:
                logger.warning(
                    "Transient failure sending into resolved conversation_id=%s for appt %s — "
                    "NOT falling back (worker backoff will retry the same conversation)",
                    history.conversation_id,
                    appt.id,
                )
                return False
            logger.warning(
                "Chatwoot rejected send into resolved conversation_id=%s for appt %s — "
                "falling back to a new conversation",
                history.conversation_id,
                appt.id,
            )

    # Fallback: resolver miss, non-numeric conversation_id, OR Chatwoot definitively
    # rejected the resolved conversation.
    new_conversation_id, success = await chatwoot.create_conversation_with_template(
        customer_phone=phone,
        template_name=template_name,
        body_params=body_params,
        category=category,
        language=language,
        fallback_content=fallback_content,
    )
    if not success or new_conversation_id is None:
        return False

    new_history_id = await _create_fallback_history(appt.customer_id, new_conversation_id)
    if new_history_id is not None:
        await _persist_sent_message(new_history_id, fallback_content)

    return True
