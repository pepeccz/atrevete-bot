"""
Conversation inbox service — orchestrates human-agent inbox operations.

This service encapsulates the business logic for admin/stylist users interacting
with customer WhatsApp conversations from the inbox UI:
  - Sending free-text and template messages
  - Pausing / resuming the bot per conversation
  - Escalating conversations

Dependencies (injected at construction time):
  - ``session``: an active ``AsyncSession`` from the request lifecycle.
  - ``chatwoot_client``: a ``ChatwootClient`` instance (or compatible async client).
  - ``redis_client``: a Redis client instance (injected where needed by callers).

Usage::

    service = ConversationInboxService(session=session, chatwoot_client=cw_client)
    msg = await service.send_text_message(conv_id, text="Hola", author=current_user)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.template_catalog import get_template_def, is_approved, render_body
from api.services.window_service import compute_window_open
from database.models import (
    AdminUser,
    ConversationHistory,
    ConversationMessage,
    ConversationMessageRole,
    Escalation,
    EscalationSource,
    EscalationStatus,
)

logger = logging.getLogger(__name__)

# TTL for the pending injection Redis flag (10 minutes)
PENDING_INJECTION_TTL_SECONDS = 600


class ConversationInboxService:
    """Business logic for human-agent inbox operations.

    All methods are ``async``.  Each method that writes data commits its own
    transaction before returning (callers do not need a separate ``session.commit()``).

    Args:
        session: Async SQLAlchemy session for this request.
        chatwoot_client: Pre-configured Chatwoot API client instance.
    """

    def __init__(self, session: AsyncSession, chatwoot_client: Any) -> None:
        self._session = session
        self._chatwoot = chatwoot_client

    async def _get_history(self, conversation_id: str) -> ConversationHistory:
        """Fetch the ConversationHistory row by either UUID PK or Chatwoot id string.

        Admin-panel callers pass ``ConversationHistory.id`` (UUID string) since
        that's what the listing endpoint exposes. Internal callers (resume
        injection from the webhook) pass ``ConversationHistory.conversation_id``
        (Chatwoot integer as string). This method accepts both: it tries to
        parse as UUID first, then falls back to the string column lookup.

        Args:
            conversation_id: UUID string OR Chatwoot conversation_id string.

        Raises:
            ValueError: If no ConversationHistory row exists for either match.
        """
        from uuid import UUID as _UUID

        history: ConversationHistory | None = None

        try:
            uuid_value = _UUID(conversation_id)
        except (ValueError, TypeError):
            uuid_value = None

        if uuid_value is not None:
            result = await self._session.execute(
                select(ConversationHistory).where(ConversationHistory.id == uuid_value)
            )
            history = result.scalar_one_or_none()

        if history is None:
            result = await self._session.execute(
                select(ConversationHistory).where(
                    ConversationHistory.conversation_id == conversation_id
                )
            )
            history = result.scalar_one_or_none()

        if history is None:
            raise ValueError(f"Conversation '{conversation_id}' not found.")
        return history

    async def send_text_message(
        self,
        conversation_id: str,
        text: str,
        author: AdminUser,
    ) -> ConversationMessage:
        """Send a free-text message to the customer via Chatwoot and persist it.

        Business rules:
        - Window must be open (``compute_window_open`` returns ``True``).
        - Calls ``ChatwootClient.send_message(conversation_id, text)``.
        - Persists ``ConversationMessage(role='human_agent', author_user_id=author.id,
          content=text)``.
        - Commits the session and returns the ORM row.

        Args:
            conversation_id: The Chatwoot / LangGraph conversation identifier string
                (NOT the ``ConversationHistory`` UUID PK).
            text: The message body (1–4096 characters, validated by the endpoint).
            author: The ``AdminUser`` sending the message.

        Returns:
            The persisted ``ConversationMessage`` ORM object.

        Raises:
            ValueError: If the 24h messaging window is closed.
            RuntimeError: If the Chatwoot API call fails.
        """
        history = await self._get_history(conversation_id)

        window_open, _ = await compute_window_open(self._session, history.id)
        if not window_open:
            raise ValueError(
                "The 24h WhatsApp messaging window is closed for this conversation. "
                "Use a Meta-approved template instead."
            )

        # Send via Chatwoot — conversation_id from Chatwoot is an int
        cw_conv_id = int(history.conversation_id)
        success = await self._chatwoot.send_message(
            customer_phone="",  # not needed when conversation_id is provided
            message=text,
            conversation_id=cw_conv_id,
        )
        if not success:
            raise RuntimeError(
                f"Chatwoot API failed to send message for conversation '{conversation_id}'."
            )

        now = datetime.now(tz=UTC)
        msg = ConversationMessage(
            id=uuid4(),
            conversation_history_id=history.id,
            role=ConversationMessageRole.HUMAN_AGENT.value,
            content=text,
            author_user_id=author.id,
            created_at=now,
        )
        self._session.add(msg)
        await self._session.commit()
        await self._session.refresh(msg)

        logger.info(
            "Human-agent message persisted",
            extra={
                "conversation_id": conversation_id,
                "author_user_id": str(author.id),
                "message_id": str(msg.id),
            },
        )
        return msg

    async def send_template(
        self,
        conversation_id: str,
        template_name: str,
        params: dict[str, str],
        author: AdminUser,
    ) -> ConversationMessage:
        """Send a Meta-approved template message and persist it.

        Business rules:
        - Template must be registered and approved (``is_approved(template_name)``).
        - Calls the Chatwoot template endpoint with the rendered body.
        - Persists ``ConversationMessage`` using the rendered body as content.

        Args:
            conversation_id: Chatwoot / LangGraph conversation identifier string.
            template_name: Machine-readable template name from the catalog.
            params: Parameter dict matching the template's ``ParamDef`` list.
            author: The ``AdminUser`` sending the message.

        Returns:
            The persisted ``ConversationMessage`` ORM object.

        Raises:
            KeyError: If ``template_name`` is not in the catalog or required params missing.
            ValueError: If the template is not yet approved by Meta.
            RuntimeError: If the Chatwoot API call fails.
        """
        # Validate template exists (raises KeyError if unknown)
        template_def = get_template_def(template_name)

        if not is_approved(template_name):
            raise ValueError(
                f"Template '{template_name}' is not yet approved by Meta. "
                "It cannot be sent until approval is granted."
            )

        # Render the local body string for DB storage (may raise KeyError on missing params)
        rendered_body = render_body(template_name, params)

        history = await self._get_history(conversation_id)
        cw_conv_id = int(history.conversation_id)

        # Chatwoot template endpoint via send_template_message
        # body_params uses positional keys matching the template param order
        positional_params = {
            str(i + 1): params.get(p.name, "") for i, p in enumerate(template_def.params)
        }
        success = await self._chatwoot.send_template_message(
            customer_phone="",
            template_name=template_name,
            body_params=positional_params,
            conversation_id=cw_conv_id,
            fallback_content=rendered_body,
        )
        if not success:
            raise RuntimeError(
                f"Chatwoot template API failed for template '{template_name}', "
                f"conversation '{conversation_id}'."
            )

        now = datetime.now(tz=UTC)
        msg = ConversationMessage(
            id=uuid4(),
            conversation_history_id=history.id,
            role=ConversationMessageRole.HUMAN_AGENT.value,
            content=rendered_body,
            author_user_id=author.id,
            created_at=now,
        )
        self._session.add(msg)
        await self._session.commit()
        await self._session.refresh(msg)

        logger.info(
            "Human-agent template message persisted",
            extra={
                "conversation_id": conversation_id,
                "template_name": template_name,
                "author_user_id": str(author.id),
                "message_id": str(msg.id),
            },
        )
        return msg

    async def pause(
        self,
        conversation_id: str,
        source: str,
        author: AdminUser,
    ) -> dict[str, Any]:
        """Pause the bot for a conversation (toggle atencion_automatica=False).

        Business rules:
        - Calls ``ChatwootClient.update_conversation_attributes(atencion_automatica=False)``.
        - Sets ``ConversationHistory.paused_at = now()`` in DB.
        - Creates ``Escalation(source='manual')`` row ONLY when ``source == 'manual'``
          (i.e., the takeover modal was confirmed by the user).
        - Commits and returns ``{paused_at, escalation_id?}``.

        Args:
            conversation_id: Chatwoot / LangGraph conversation identifier string.
            source: ``"manual"`` (modal-confirmed takeover) or ``"toggle"``
                (direct toggle without modal; no Escalation row created).
            author: The ``AdminUser`` performing the pause.

        Returns:
            Dict with ``paused_at: datetime`` and optionally ``escalation_id: UUID``.

        Raises:
            ValueError: If the conversation is already paused (409 territory).
            RuntimeError: If the Chatwoot API call fails.
        """
        history = await self._get_history(conversation_id)

        if history.paused_at is not None and history.resumed_at is None:
            raise ValueError(f"Conversation '{conversation_id}' is already paused.")

        cw_conv_id = int(history.conversation_id)
        try:
            await self._chatwoot.update_conversation_attributes(
                conversation_id=cw_conv_id,
                attributes={"atencion_automatica": False},
            )
        except Exception as exc:
            raise RuntimeError(
                f"Chatwoot API failed to set atencion_automatica=False: {exc}"
            ) from exc

        now = datetime.now(tz=UTC)
        history.paused_at = now

        escalation_id: UUID | None = None
        if source == "manual":
            # Fetch customer phone from ConversationHistory metadata or default to empty
            customer_phone = history.metadata_.get("sender_phone", "") if history.metadata_ else ""
            escalation = Escalation(
                id=uuid4(),
                conversation_id=history.conversation_id,
                customer_id=history.customer_id,
                customer_phone=customer_phone,
                reason="Manual takeover by admin/stylist",
                source=EscalationSource.MANUAL,
                status=EscalationStatus.TRIGGERED,
            )
            self._session.add(escalation)
            escalation_id = escalation.id

        await self._session.commit()

        logger.info(
            "Conversation paused",
            extra={
                "conversation_id": conversation_id,
                "source": source,
                "author_user_id": str(author.id),
                "escalation_id": str(escalation_id) if escalation_id else None,
            },
        )

        result: dict[str, Any] = {"paused_at": now}
        if escalation_id is not None:
            result["escalation_id"] = escalation_id
        return result

    async def resume(
        self,
        conversation_id: str,
        author: AdminUser,
        redis_client: Any | None = None,
    ) -> dict[str, Any]:
        """Resume the bot for a conversation (toggle atencion_automatica=True).

        Business rules:
        - Calls ``ChatwootClient.update_conversation_attributes(atencion_automatica=True)``.
        - Sets ``ConversationHistory.resumed_at = now()``, clears ``paused_at = NULL``.
        - Auto-resolves any open ``Escalation`` row
          (``status='resolved', resolved_by_user_id=author.id, resolved_at=now()``).
        - Sets Redis key ``pending_injection:v2:{conversation_id}`` with TTL 600s
          (deferred context injection on the next inbound — ADR-2).
        - Commits and returns ``{resumed_at, pending_injection_ttl_seconds: 600}``.

        Args:
            conversation_id: Chatwoot / LangGraph conversation identifier string.
            author: The ``AdminUser`` performing the resume.
            redis_client: Redis client for setting the pending injection flag.

        Returns:
            Dict with ``resumed_at: datetime`` and ``pending_injection_ttl_seconds: int``.

        Raises:
            ValueError: If the conversation is not currently paused (409 territory).
            RuntimeError: If the Chatwoot API call or Redis write fails.
        """
        history = await self._get_history(conversation_id)

        if history.paused_at is None:
            raise ValueError(f"Conversation '{conversation_id}' is not currently paused.")

        cw_conv_id = int(history.conversation_id)
        try:
            await self._chatwoot.update_conversation_attributes(
                conversation_id=cw_conv_id,
                attributes={"atencion_automatica": True},
            )
        except Exception as exc:
            raise RuntimeError(
                f"Chatwoot API failed to set atencion_automatica=True: {exc}"
            ) from exc

        now = datetime.now(tz=UTC)
        history.resumed_at = now
        history.paused_at = None

        # Auto-resolve any open Escalation for this conversation
        escalation_result = await self._session.execute(
            select(Escalation).where(
                Escalation.conversation_id == history.conversation_id,
                Escalation.status == EscalationStatus.TRIGGERED,
            )
        )
        open_escalation = escalation_result.scalar_one_or_none()
        if open_escalation is not None:
            open_escalation.status = EscalationStatus.RESOLVED
            open_escalation.resolved_at = now
            open_escalation.resolved_by_user_id = author.id

        await self._session.commit()

        # Set pending injection flag in Redis (TTL 600s). Must key by the
        # Chatwoot string id since resume_injection.maybe_inject_pending_context
        # is invoked from the webhook with payload.conversation.id (Chatwoot int).
        if redis_client is not None:
            try:
                injection_key = f"pending_injection:v2:{history.conversation_id}"
                await redis_client.set(injection_key, "1", ex=PENDING_INJECTION_TTL_SECONDS)
                logger.info(
                    "Pending injection flag set",
                    extra={
                        "conversation_id": history.conversation_id,
                        "ttl_seconds": PENDING_INJECTION_TTL_SECONDS,
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Failed to set pending_injection Redis flag: %s — injection will not occur",
                    exc,
                    extra={"conversation_id": history.conversation_id},
                )

        logger.info(
            "Conversation resumed",
            extra={
                "conversation_id": conversation_id,
                "author_user_id": str(author.id),
            },
        )

        return {
            "resumed_at": now,
            "pending_injection_ttl_seconds": PENDING_INJECTION_TTL_SECONDS,
        }

    async def escalate(
        self,
        conversation_id: str,
        reason: str,
        note: str | None,
        author: AdminUser,
    ) -> dict[str, Any]:
        """Create an explicit escalation record for a conversation.

        Business rules:
        - Inserts ``Escalation(source='manual', status='triggered')``.
        - Does NOT pause the bot (caller is responsible for pausing if needed).
        - Commits and returns ``{escalation_id: UUID}``.

        Args:
            conversation_id: Chatwoot / LangGraph conversation identifier string.
            reason: Short reason string stored in ``Escalation.reason``.
            note: Optional longer note stored in ``Escalation.issue_summary``.
            author: The ``AdminUser`` triggering the escalation.

        Returns:
            Dict with ``escalation_id: UUID``.

        Raises:
            RuntimeError: On unexpected DB write failure.
        """
        history = await self._get_history(conversation_id)
        customer_phone = history.metadata_.get("sender_phone", "") if history.metadata_ else ""

        escalation = Escalation(
            id=uuid4(),
            conversation_id=history.conversation_id,
            customer_id=history.customer_id,
            customer_phone=customer_phone,
            reason=reason,
            source=EscalationSource.MANUAL,
            status=EscalationStatus.TRIGGERED,
            issue_summary=note,
        )
        self._session.add(escalation)
        await self._session.commit()

        logger.info(
            "Explicit escalation created",
            extra={
                "conversation_id": conversation_id,
                "escalation_id": str(escalation.id),
                "author_user_id": str(author.id),
            },
        )

        return {"escalation_id": escalation.id}
