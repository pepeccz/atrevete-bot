"""Chatwoot webhook route handler."""

import hmac
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import aiohttp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from groq import APIError, RateLimitError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.chatwoot_webhook import (
    ChatwootMessageEvent,
    ChatwootWebhookPayload,
)
from shared.audio_conversion import convert_ogg_to_wav
from shared.audio_transcription import get_transcription_service
from shared.chatwoot_client import ChatwootClient
from shared.config import get_settings
from shared.redis_client import (
    INCOMING_STREAM,
    add_to_stream,
    get_redis_client,
    publish_to_channel,
)
from shared.settings_service import get_settings_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Conversation history upsert
# ============================================================================


async def upsert_conversation_history(
    session: AsyncSession,
    payload: ChatwootWebhookPayload,
    message_text: str | None = None,
    chatwoot_message_id: int | None = None,
    attachments_payload: list[dict] | None = None,
) -> None:
    """
    UPSERT a ConversationHistory row + ConversationMessage child for inbound message.

    - INSERT parent on first message; UPDATE ended_at on subsequent.
    - Inserts a ConversationMessage child (role='user') with idempotency by
      chatwoot_message_id when present, else by (role, content) within the conversation.
    - Recomputes parent.message_count from actual children to stay consistent
      with the archiver fallback.
    - PR-3a: when ``attachments_payload`` is provided, persists attachment rows after
      the ConversationMessage flush.  Message is inserted even when ``message_text``
      is None/empty as long as attachments are present (attachment-only messages).
    """
    from sqlalchemy import func

    from database.models import ConversationHistory, ConversationMessage, Customer

    conversation_id_str = str(payload.conversation.id)
    sender_name = payload.sender.name or ""
    sender_phone = payload.sender.phone_number

    customer_id = None
    if sender_phone:
        customer_result = await session.execute(
            select(Customer.id).where(Customer.phone == sender_phone)
        )
        customer_id = customer_result.scalar_one_or_none()

    result = await session.execute(
        select(ConversationHistory).where(
            ConversationHistory.conversation_id == conversation_id_str
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.now(tz=UTC)

    initial_metadata: dict[str, Any] = {}
    if sender_name:
        initial_metadata["sender_name"] = sender_name
    if sender_phone:
        initial_metadata["sender_phone"] = sender_phone

    if existing is None:
        parent = ConversationHistory(
            conversation_id=conversation_id_str,
            customer_id=customer_id,
            started_at=now,
            ended_at=now,
            message_count=0,
            metadata_=initial_metadata,
        )
        session.add(parent)
        await session.flush()
    else:
        parent = existing
        parent.ended_at = now
        if parent.customer_id is None and customer_id is not None:
            parent.customer_id = customer_id
        # Mirror sender_name and sender_phone from WhatsApp into metadata.
        # Used by the admin inbox CustomerCard to show contact info when the
        # conversation is not yet linked to a customers row.
        if sender_name and not parent.metadata_.get("sender_name"):
            parent.metadata_ = {**parent.metadata_, "sender_name": sender_name}
        if sender_phone and not parent.metadata_.get("sender_phone"):
            parent.metadata_ = {**parent.metadata_, "sender_phone": sender_phone}

    # Mirror Chatwoot's can_reply (24h WhatsApp window indicator) on both new
    # and updated rows. window_service falls back to message-timestamp
    # computation when capture is missing or older than 24h.
    if payload.conversation.can_reply is not None:
        parent.can_reply = payload.conversation.can_reply
        parent.can_reply_captured_at = now
        await session.flush()

    # Insert user child idempotently
    # PR-3a: persist message when EITHER text OR attachments are present.
    # Attachment-only messages (content=null in Chatwoot) use empty-string content.
    _has_content = bool(message_text) or bool(attachments_payload)
    if _has_content:
        # Normalise: use empty string when the message has no text body
        _content = message_text or ""
        is_dup = False
        if chatwoot_message_id is not None:
            dup_result = await session.execute(
                select(ConversationMessage.id).where(
                    ConversationMessage.conversation_history_id == parent.id,
                    ConversationMessage.chatwoot_message_id == chatwoot_message_id,
                )
            )
            is_dup = dup_result.scalar_one_or_none() is not None
        else:
            dup_result = await session.execute(
                select(ConversationMessage.id).where(
                    ConversationMessage.conversation_history_id == parent.id,
                    ConversationMessage.role == "user",
                    ConversationMessage.content == _content,
                )
            )
            is_dup = dup_result.scalar_one_or_none() is not None

        if not is_dup:
            msg_row = ConversationMessage(
                conversation_history_id=parent.id,
                role="user",
                content=_content,
                chatwoot_message_id=chatwoot_message_id,
                created_at=now,
                author_type="user",  # PR-1: stamp inbound as user
            )
            session.add(msg_row)
            await session.flush()

            # PR-3a: persist attachment rows now that msg_row.id is available
            if attachments_payload:
                await _persist_attachments(
                    message_id=msg_row.id,
                    attachments_payload=attachments_payload,
                    session=session,
                )

    count_result = await session.execute(
        select(func.count())
        .select_from(ConversationMessage)
        .where(ConversationMessage.conversation_history_id == parent.id)
    )
    parent.message_count = count_result.scalar() or 0


# =============================================================================
# PR-3a: attachment persistence helper
# =============================================================================


async def _persist_attachments(
    *,
    message_id: UUID,
    attachments_payload: list[dict] | None,
    session: AsyncSession,
) -> int:
    """Persist attachments from a Chatwoot webhook payload.

    Tolerant — skips items without ``data_url``, defaults safe for missing
    fields.  Reads from the top-level ``payload.attachments[]`` which Chatwoot
    places at the event level (not inside ``conversation.messages``).

    Returns the count of rows persisted.
    """
    from database.models import MessageAttachment

    if not attachments_payload:
        return 0

    count = 0
    for position, att in enumerate(attachments_payload):
        url = att.get("data_url")
        if not url:
            logger.info(
                "Skipping attachment at position %d for message %s — data_url missing",
                position,
                message_id,
                extra={"message_id": str(message_id), "attachment": att},
            )
            continue

        row = MessageAttachment(
            message_id=message_id,
            file_type=att.get("file_type") or "file",
            url=url,
            thumb_url=att.get("thumb_url") or None,
            content_type=att.get("content_type") or None,
            filename=att.get("file_name") or att.get("filename") or None,
            size_bytes=att.get("file_size") or None,
            width=att.get("width") or None,
            height=att.get("height") or None,
            position=position,
        )
        session.add(row)
        count += 1

    return count


# =============================================================================
# PR-1: delivery_failed webhook hook
# =============================================================================

STATUS_LOGGER = logging.getLogger("webhook.message_status")


async def _handle_message_status_event(payload_body: dict, db_session: Any) -> bool:
    """Handle Chatwoot ``message_updated`` events for delivery failure tracking.

    Sets ``delivery_failed=True`` on the matching ``ConversationMessage`` row
    when ``payload.status == 'failed'``.  All other statuses are silently
    ignored (non-failure events are common and expected).

    Tolerant by design:
    - If the event is not ``message_updated``, returns False (no-op).
    - If ``payload.status`` is not ``'failed'``, returns False (no-op).
    - If the message row has not been persisted yet (rare race), logs and skips.
    - Idempotent: setting ``True`` again is a no-op in the DB.

    Args:
        payload_body: Raw parsed webhook payload dict.
        db_session: Active async SQLAlchemy session.

    Returns:
        True if a row was updated; False otherwise (ignored or not found).
    """
    from sqlalchemy import update as sa_update

    from database.models import ConversationMessage

    event = payload_body.get("event")
    if event != "message_updated":
        return False

    # Extract status from the message-level object — Chatwoot sends it under
    # the top-level "status" key or nested in "message.status".
    # Tolerate both shapes.
    status = payload_body.get("status") or (payload_body.get("message") or {}).get("status")

    if status != "failed":
        STATUS_LOGGER.debug("message_updated with non-failed status=%r — ignored", status)
        return False

    # Locate the ConversationMessage by chatwoot_message_id
    chatwoot_msg_id = payload_body.get("id") or (payload_body.get("message") or {}).get("id")
    if chatwoot_msg_id is None:
        STATUS_LOGGER.warning("message_updated: no message id found in payload — skipped")
        return False

    STATUS_LOGGER.info("Delivery failure event received for chatwoot_message_id=%s", chatwoot_msg_id)

    stmt = (
        sa_update(ConversationMessage)
        .where(ConversationMessage.chatwoot_message_id == int(chatwoot_msg_id))
        .values(delivery_failed=True)
        .execution_options(synchronize_session="fetch")
    )
    result = await db_session.execute(stmt)
    updated = result.rowcount or 0

    if updated == 0:
        STATUS_LOGGER.warning(
            "message_updated: chatwoot_message_id=%s not found in DB — possible race",
            chatwoot_msg_id,
        )
        return False

    STATUS_LOGGER.info(
        "delivery_failed=True set for chatwoot_message_id=%s (%d row)",
        chatwoot_msg_id,
        updated,
    )
    return True


# Idempotency constants
IDEMPOTENCY_TTL = 300  # 5 minutes
IDEMPOTENCY_PREFIX = "idempotency:chatwoot:"

# Rate limit constants
RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes
RATE_LIMIT_MAX_MESSAGES = 20
RATE_LIMIT_PREFIX = "wa_rate_limit:"

# Audio size limit
MAX_AUDIO_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


async def check_conversation_rate_limit(conversation_id: int) -> bool:
    """Check per-conversation rate limit. Returns True if limit exceeded."""
    import time

    window = int(time.time()) // RATE_LIMIT_WINDOW_SECONDS
    key = f"{RATE_LIMIT_PREFIX}{conversation_id}:{window}"
    try:
        client = get_redis_client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, RATE_LIMIT_WINDOW_SECONDS)
        return count > RATE_LIMIT_MAX_MESSAGES
    except Exception as e:
        logger.warning("Rate limit Redis error: %s — failing open", e)
        return False


async def check_and_set_idempotency(message_id: int) -> bool:
    """
    Check if message has already been processed (idempotency check).

    Uses Redis SETNX with TTL to prevent duplicate processing.
    If Chatwoot retries a webhook, the message_id will already exist.

    Args:
        message_id: Chatwoot message ID

    Returns:
        True if message is a duplicate (already processed)
        False if message is new (should be processed)
    """
    client = get_redis_client()
    key = f"{IDEMPOTENCY_PREFIX}{message_id}"

    # SETNX returns True if key was set (new message), False if already exists (duplicate)
    was_set = await client.setnx(key, "1")

    if was_set:
        # New message - set TTL and allow processing
        await client.expire(key, IDEMPOTENCY_TTL)
        return False  # Not a duplicate

    # Key already exists - this is a duplicate
    logger.info(f"Duplicate message detected: {message_id}")
    return True  # Is a duplicate


@router.post("/chatwoot/{token}")
async def receive_chatwoot_webhook(
    request: Request,
    token: str,
) -> JSONResponse:
    """
    Receive and process Chatwoot webhook events.

    Authentication: Token in URL path must match CHATWOOT_WEBHOOK_TOKEN.
    Configure in Chatwoot: https://your-domain.com/webhook/chatwoot/{your_secret_token}

    Only processes 'message_created' events with 'incoming' message type.
    Valid messages are enqueued to Redis 'incoming_messages' channel.

    Gate refactor (FR-WEBHOOK-1 through FR-WEBHOOK-5 — PR-2):
    - DB upsert and audio transcription ALWAYS run (before any gate check).
    - Global AI off: persists DB row then returns WITHOUT publishing to Redis.
    - Per-conversation gate (atencion_automatica=False): only gates the Redis publish.
    - Resume injection: checked between DB upsert and Redis publish.

    Args:
        request: FastAPI request object
        token: Secret token from URL path

    Returns:
        JSONResponse with 200 OK status

    Raises:
        HTTPException 401: Invalid or missing token
    """
    settings = get_settings()

    # Step 1: Token auth
    if not hmac.compare_digest(token, settings.CHATWOOT_WEBHOOK_TOKEN):
        logger.warning(f"Invalid Chatwoot webhook token attempted from IP: {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid token")

    # Step 2: Payload parse + event/incoming filter
    body = await request.body()
    body_str = body.decode("utf-8")
    logger.info(f"Raw webhook payload: {body_str[:2000]}")
    logger.debug(f"Full webhook payload: {body_str}")

    try:
        payload = ChatwootWebhookPayload.model_validate_json(body)
    except Exception as e:
        logger.error(
            f"Failed to parse webhook payload: {e}",
            exc_info=True,
            extra={"payload_preview": body_str[:1000]},
        )
        raise HTTPException(status_code=400, detail=f"Invalid payload format: {str(e)}") from e

    # PR-1: Handle message_updated delivery-failure events before the event filter.
    # This is tolerant — if no row is updated (rare race, non-failure status) we
    # simply return 200 without further processing.
    if payload.event == "message_updated":
        try:
            from database.connection import get_async_session

            async with get_async_session() as db_session:
                await _handle_message_status_event(
                    payload_body=body_str and __import__("json").loads(body_str) or {},
                    db_session=db_session,
                )
                await db_session.commit()
        except Exception as e:
            STATUS_LOGGER.warning(
                "Failed to handle message_updated event: %s", e, exc_info=True
            )
        return JSONResponse(status_code=200, content={"status": "message_updated_handled"})

    # Filter: Only process message_created events
    if payload.event != "message_created":
        logger.debug(f"Ignoring non-message event: {payload.event}")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Filter: Only process conversations with messages
    if not payload.conversation.messages:
        logger.debug(f"Ignoring conversation {payload.conversation.id} with no messages")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Get the last (most recent) message from the array
    last_message = payload.conversation.messages[-1]

    # Filter: Only process incoming messages (message_type == 0)
    if last_message.message_type != 0:
        logger.debug(f"Ignoring non-incoming message: message_type={last_message.message_type}")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Step 3: Idempotency check
    if await check_and_set_idempotency(last_message.id):
        return JSONResponse(status_code=200, content={"status": "duplicate"})

    # Step 4: Per-conversation rate limit check (before transcription to avoid wasted CPU)
    if await check_conversation_rate_limit(payload.conversation.id):
        try:
            chatwoot_client = ChatwootClient()
            await chatwoot_client.send_message(
                customer_phone=payload.sender.phone_number,
                message="Estás enviando mensajes muy rápido 😅 Espera un momento y vuelve a escribirme. 🙏",
                conversation_id=payload.conversation.id,
            )
        except Exception:
            pass
        return JSONResponse(status_code=200, content={"status": "rate_limited"})

    # Step 5: Phone guard
    if not payload.sender.phone_number:
        logger.warning(f"Message {last_message.id} has no phone number, ignoring")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Step 6: Audio transcription (runs BEFORE the gate — FR-WEBHOOK-2)
    # Initialize message text and audio tracking fields
    message_text = last_message.content or ""
    is_audio_transcription = False
    audio_url = None
    # PR-3a: when True the message was persisted but must NOT be published to Redis
    _skip_redis_non_audio = False

    # Check if message has audio attachments (attachments are in message.attachments)
    # Also check root-level attachments for backward compatibility
    message_attachments = last_message.attachments or payload.attachments
    if message_attachments:
        # Filter: Ignore messages with non-audio attachments (images, videos, files)
        # We only want to process text messages or audio messages for transcription
        non_audio_attachments = [att for att in message_attachments if att.file_type != "audio"]

        if non_audio_attachments:
            logger.info(
                "Ignoring message with non-audio attachments: %s found",
                len(non_audio_attachments),
                extra={
                    "conversation_id": str(payload.conversation.id),
                    "attachment_types": [att.file_type for att in non_audio_attachments],
                },
            )
            if message_text:
                # Text + non-audio attachment: process the text, ignore attachment
                logger.info("Message has text alongside non-audio attachment, processing text only")
            else:
                # PR-3a: attachment-only message — persist to DB but skip Redis publish.
                # Send a friendly reply to the customer and fall through to Step 7.
                try:
                    chatwoot_client = ChatwootClient()
                    await chatwoot_client.send_message(
                        customer_phone=payload.sender.phone_number,
                        message=(
                            "No puedo procesar imágenes ni archivos. "
                            "¿Puedes repetir tu consulta por escrito o como nota de voz? 💕"
                        ),
                        conversation_id=payload.conversation.id,
                    )
                except Exception as e:
                    logger.warning("Failed to send non-audio attachment reply: %s", e)
                _skip_redis_non_audio = True
                # Fall through to Step 7 so DB row + attachments are persisted.

        audio_attachments = [att for att in message_attachments if att.file_type == "audio"]

        if audio_attachments:
            # Process first audio attachment (WhatsApp sends one audio per message)
            audio_attachment = audio_attachments[0]
            audio_url = audio_attachment.data_url

            logger.info(
                f"Audio message detected: conversation_id={payload.conversation.id}, "
                f"attachment_id={audio_attachment.id}, url={audio_url}",
                extra={
                    "conversation_id": str(payload.conversation.id),
                    "attachment_id": audio_attachment.id,
                    "audio_url": audio_url,
                },
            )

            # Download and transcribe audio
            ogg_path = None
            wav_path = None

            try:
                # 1. Download audio from Chatwoot
                logger.debug(f"Downloading audio from: {audio_url}")
                async with aiohttp.ClientSession() as session:
                    async with session.get(audio_url) as response:
                        if response.status != 200:
                            raise Exception(f"Failed to download audio: HTTP {response.status}")
                        content_length = response.headers.get("Content-Length")
                        if content_length and int(content_length) > MAX_AUDIO_SIZE_BYTES:
                            logger.warning(
                                "Audio too large: %s bytes from conversation %s",
                                content_length,
                                payload.conversation.id,
                            )
                            try:
                                chatwoot_client = ChatwootClient()
                                await chatwoot_client.send_message(
                                    customer_phone=payload.sender.phone_number,
                                    message="El audio es demasiado largo. Por favor, envía un mensaje más corto o escribe tu consulta. 🎙️",
                                    conversation_id=payload.conversation.id,
                                )
                            except Exception:
                                pass
                            return JSONResponse(
                                status_code=200, content={"status": "audio_too_large"}
                            )
                        if content_length:
                            audio_data = await response.read()
                        else:
                            chunks = []
                            total = 0
                            async for chunk in response.content.iter_chunked(65536):
                                total += len(chunk)
                                if total > MAX_AUDIO_SIZE_BYTES:
                                    logger.warning(
                                        "Audio exceeded %d bytes mid-stream",
                                        MAX_AUDIO_SIZE_BYTES,
                                    )
                                    try:
                                        chatwoot_client = ChatwootClient()
                                        await chatwoot_client.send_message(
                                            customer_phone=payload.sender.phone_number,
                                            message="El audio es demasiado largo. Por favor, envía un mensaje más corto o escribe tu consulta. 🎙️",
                                            conversation_id=payload.conversation.id,
                                        )
                                    except Exception:
                                        pass
                                    return JSONResponse(
                                        status_code=200, content={"status": "audio_too_large"}
                                    )
                                chunks.append(chunk)
                            audio_data = b"".join(chunks)

                # 2. Save to temporary OGG file
                with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
                    temp_ogg.write(audio_data)
                    ogg_path = Path(temp_ogg.name)

                logger.debug(
                    f"Audio downloaded: {ogg_path.name}",
                    extra={
                        "conversation_id": str(payload.conversation.id),
                        "file_size_mb": len(audio_data) / (1024 * 1024),
                    },
                )

                # 3. Convert OGG → WAV for optimal compatibility
                wav_path = await convert_ogg_to_wav(ogg_path)

                # 4. Transcribe audio to text using Groq Whisper with confidence scoring
                transcription_service = get_transcription_service()
                message_text, confidence = await transcription_service.transcribe_audio(wav_path)

                # Check confidence threshold (< 0.7 indicates potential transcription error)
                if confidence < 0.7:
                    logger.warning(
                        f"Low confidence transcription: {confidence:.2f}",
                        extra={
                            "conversation_id": str(payload.conversation.id),
                            "confidence_score": confidence,
                            "transcription_preview": message_text[:100],
                        },
                    )
                    # Ask user to resend audio or send text instead
                    message_text = "[AUDIO_LOW_CONFIDENCE] Lo siento, no pude entender bien el audio. ¿Puedes enviarlo de nuevo o escribir tu mensaje en texto? 😊"
                    is_audio_transcription = False
                else:
                    is_audio_transcription = True
                    logger.info(
                        f"Audio transcribed successfully: {len(message_text)} characters, confidence: {confidence:.2f}",
                        extra={
                            "conversation_id": str(payload.conversation.id),
                            "transcription_length": len(message_text),
                            "transcription_preview": message_text[:100],
                            "confidence_score": confidence,
                        },
                    )

            except RateLimitError:
                logger.error(
                    f"Groq rate limit exceeded for conversation {payload.conversation.id}",
                    extra={"conversation_id": str(payload.conversation.id)},
                    exc_info=True,
                )
                # Fallback: Ask user to send text instead
                message_text = "[AUDIO_RATE_LIMIT] Por favor, escribe tu mensaje en texto. Estamos experimentando alta demanda de transcripciones."
                is_audio_transcription = False

            except APIError as e:
                logger.error(
                    f"Groq API error during transcription: {e}",
                    extra={"conversation_id": str(payload.conversation.id)},
                    exc_info=True,
                )
                # Fallback: Ask user to send text instead
                message_text = "[AUDIO_API_ERROR] Lo siento, no pude procesar el audio. ¿Puedes escribir tu mensaje en texto?"
                is_audio_transcription = False

            except Exception as e:
                logger.error(
                    f"Unexpected error processing audio: {e}",
                    extra={"conversation_id": str(payload.conversation.id)},
                    exc_info=True,
                )
                # Fallback: Ask user to send text instead
                message_text = "[AUDIO_ERROR] Lo siento, hubo un problema con el audio. ¿Puedes escribir tu mensaje?"
                is_audio_transcription = False

            finally:
                # Cleanup temporary files
                if ogg_path and ogg_path.exists():
                    try:
                        os.unlink(ogg_path)
                        logger.debug(f"Cleaned up: {ogg_path.name}")
                    except Exception as e:
                        logger.warning(f"Failed to cleanup OGG file: {e}")

                if wav_path and wav_path.exists():
                    try:
                        os.unlink(wav_path)
                        logger.debug(f"Cleaned up: {wav_path.name}")
                    except Exception as e:
                        logger.warning(f"Failed to cleanup WAV file: {e}")

    # Step 7: DB upsert — ALWAYS runs before gate checks (FR-WEBHOOK-1)
    # Policy change (FR-WEBHOOK-4): even when AI is globally disabled, we persist.
    try:
        from database.connection import get_async_session

        async with get_async_session() as db_session:
            cw_msg_id = None
            try:
                if payload.conversation.messages:
                    cw_msg_id = payload.conversation.messages[-1].id
            except Exception:
                cw_msg_id = None
            # PR-3a: pass top-level attachments as raw dicts so
            # _persist_attachments can access thumb_url, file_size, etc.
            raw_attachments = (
                [att.model_dump() for att in payload.attachments]
                if payload.attachments
                else None
            )
            await upsert_conversation_history(
                db_session,
                payload,
                message_text=message_text,
                chatwoot_message_id=cw_msg_id,
                attachments_payload=raw_attachments,
            )
            await db_session.commit()
    except Exception as e:
        logger.warning(
            "Failed to upsert conversation_history for conversation %s: %s",
            payload.conversation.id,
            e,
            extra={"conversation_id": str(payload.conversation.id)},
        )

    # PR-3a: attachment-only messages were persisted; skip Redis publish.
    if _skip_redis_non_audio:
        logger.info(
            "Non-audio attachment message persisted to DB — not published to Redis "
            "for conversation %s",
            payload.conversation.id,
            extra={"conversation_id": str(payload.conversation.id)},
        )
        return JSONResponse(status_code=200, content={"status": "ignored_non_audio_attachment"})

    # Step 8: System-wide AI toggle check (panic button) — fail-CLOSED
    # Policy change (FR-WEBHOOK-4): we already persisted the DB row above.
    # Now we short-circuit WITHOUT publishing to Redis.
    try:
        settings_service = await get_settings_service()
        ai_enabled = await settings_service.get("ai_agent_enabled")
        if ai_enabled is None or ai_enabled is False:
            log_level = logging.ERROR if ai_enabled is None else logging.INFO
            logger.log(
                log_level,
                "AI agent disabled — message persisted to DB but NOT published to Redis for conversation %s%s",
                payload.conversation.id,
                " (setting missing — fail-closed)" if ai_enabled is None else "",
                extra={"conversation_id": str(payload.conversation.id)},
            )
            return JSONResponse(
                status_code=200,
                content={"status": "ignored_ai_disabled"},
            )
    except Exception as e:
        logger.error(
            "SettingsService error checking ai_agent_enabled — fail-closed: %s",
            e,
            extra={"conversation_id": str(payload.conversation.id)},
            exc_info=True,
        )
        return JSONResponse(
            status_code=200,
            content={"status": "ignored_ai_disabled"},
        )

    # Step 9: Per-conversation gate — Check atencion_automatica custom attribute
    # This allows toggling AI bot on/off per conversation.
    # Only the Redis publish step is gated (FR-WEBHOOK-3).
    atencion_automatica = payload.conversation.custom_attributes.get("atencion_automatica")

    if atencion_automatica is None:
        # First message from this customer - enable bot and continue processing
        logger.info(
            f"First message for conversation {payload.conversation.id}: "
            f"setting atencion_automatica=true",
            extra={
                "conversation_id": str(payload.conversation.id),
                "customer_phone": payload.sender.phone_number,
            },
        )

        # Update conversation to enable bot
        try:
            chatwoot_client = ChatwootClient()
            await chatwoot_client.update_conversation_attributes(
                conversation_id=payload.conversation.id, attributes={"atencion_automatica": True}
            )
            logger.info(f"Successfully enabled bot for conversation {payload.conversation.id}")
        except Exception as e:
            # Log warning but continue processing - don't block first message
            logger.warning(
                f"Failed to set atencion_automatica for conversation {payload.conversation.id}: {e}",
                extra={
                    "conversation_id": str(payload.conversation.id),
                    "error": str(e),
                },
                exc_info=True,
            )

    # Step 10: Resume injection hook (FR-WEBHOOK-5)
    # Check if a pending injection flag exists and inject paused-window messages
    # into LangGraph state before publishing to the Redis Stream.
    conversation_id_str = str(payload.conversation.id)
    if atencion_automatica is not False:
        # Only attempt injection when bot is ON (or just enabled above)
        try:
            redis_client = get_redis_client()
            from api.services.resume_injection import maybe_inject_pending_context
            from database.connection import get_async_session as _get_session

            async with _get_session() as inject_session:
                await maybe_inject_pending_context(
                    conversation_id=conversation_id_str,
                    session=inject_session,
                    redis_client=redis_client,
                )
        except Exception as inject_err:
            logger.warning(
                "Resume injection error for conversation %s: %s — proceeding to publish",
                conversation_id_str,
                inject_err,
                extra={"conversation_id": conversation_id_str},
            )

    # Step 11: Per-conversation gate — only Redis publish is gated (FR-WEBHOOK-3)
    if atencion_automatica is False:
        # Bot is disabled for this conversation - message was persisted but NOT published
        logger.info(
            f"Bot paused for conversation {payload.conversation.id}: "
            f"message persisted to DB but NOT published to Redis",
            extra={
                "conversation_id": str(payload.conversation.id),
                "customer_phone": payload.sender.phone_number,
            },
        )
        return JSONResponse(status_code=200, content={"status": "ignored_auto_attention_disabled"})

    # If atencion_automatica is True or was just set, continue to publish
    logger.debug(
        f"Processing message for conversation {payload.conversation.id}: "
        f"atencion_automatica={atencion_automatica}",
        extra={
            "conversation_id": str(payload.conversation.id),
            "atencion_automatica": atencion_automatica,
        },
    )

    # Step 12: Create message event for Redis and publish
    message_event = ChatwootMessageEvent(
        conversation_id=conversation_id_str,
        customer_phone=payload.sender.phone_number,  # Will be normalized to E.164
        message_text=message_text,
        sender_name=payload.sender.name,
        customer_name=payload.sender.name,  # DEPRECATED: kept for rolling deploy compatibility
        is_audio_transcription=is_audio_transcription,
        audio_url=audio_url,
    )

    logger.info(
        f"Parsed message event: conversation_id={message_event.conversation_id}, "
        f"phone={message_event.customer_phone}, sender_name={message_event.sender_name}, "
        f"text='{message_event.message_text[:100]}'"
    )

    # Log full message content for debugging
    logger.debug(
        f"Full incoming message: '{message_event.message_text}'",
        extra={
            "conversation_id": message_event.conversation_id,
            "customer_phone": message_event.customer_phone,
            "message_length": len(message_event.message_text) if message_event.message_text else 0,
        },
    )

    # Publish to Redis (using Streams or Pub/Sub based on config)
    if settings.USE_REDIS_STREAMS:
        # Redis Streams: Persistent with acknowledgment
        stream_msg_id = await add_to_stream(
            INCOMING_STREAM,
            message_event.model_dump(),
        )
        logger.info(
            f"Chatwoot message added to stream: conversation_id={message_event.conversation_id}, "
            f"phone={message_event.customer_phone}, stream_msg_id={stream_msg_id}"
        )
    else:
        # Legacy Pub/Sub: Fire-and-forget
        await publish_to_channel(
            "incoming_messages",
            message_event.model_dump(),
        )
        logger.info(
            f"Chatwoot message published (pub/sub): conversation_id={message_event.conversation_id}, "
            f"phone={message_event.customer_phone}"
        )

    # Log Redis payload for debugging
    logger.debug(
        f"Redis payload: {message_event.model_dump()}",
        extra={"conversation_id": message_event.conversation_id},
    )

    return JSONResponse(status_code=200, content={"status": "received"})
