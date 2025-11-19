"""Chatwoot webhook route handler."""

import aiohttp
import hmac
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from groq import RateLimitError, APIError

from shared.chatwoot_client import ChatwootClient
from api.models.chatwoot_webhook import (
    ChatwootMessageEvent,
    ChatwootWebhookPayload,
)
from shared.audio_conversion import convert_ogg_to_wav
from shared.audio_transcription import get_transcription_service
from shared.config import get_settings
from shared.redis_client import publish_to_channel

logger = logging.getLogger(__name__)

router = APIRouter()


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

    Args:
        request: FastAPI request object
        token: Secret token from URL path

    Returns:
        JSONResponse with 200 OK status

    Raises:
        HTTPException 401: Invalid or missing token
    """
    settings = get_settings()

    # Validate token using timing-safe comparison
    if not hmac.compare_digest(token, settings.CHATWOOT_WEBHOOK_TOKEN):
        logger.warning(
            f"Invalid Chatwoot webhook token attempted from IP: {request.client.host}"
        )
        raise HTTPException(status_code=401, detail="Invalid token")

    # Read and parse webhook payload
    body = await request.body()
    body_str = body.decode('utf-8')
    logger.info(f"Raw webhook payload: {body_str[:2000]}")
    logger.debug(f"Full webhook payload: {body_str}")

    try:
        payload = ChatwootWebhookPayload.model_validate_json(body)
    except Exception as e:
        logger.error(
            f"Failed to parse webhook payload: {e}",
            exc_info=True,
            extra={"payload_preview": body_str[:1000]}
        )
        raise HTTPException(status_code=400, detail=f"Invalid payload format: {str(e)}")

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
        logger.debug(
            f"Ignoring non-incoming message: message_type={last_message.message_type}"
        )
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Ensure phone number exists (use sender from root level, not from message)
    if not payload.sender.phone_number:
        logger.warning(f"Message {last_message.id} has no phone number, ignoring")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # Filter: Check atencion_automatica custom attribute
    # This allows toggling AI bot on/off per conversation
    atencion_automatica = payload.conversation.custom_attributes.get("atencion_automatica")

    if atencion_automatica is False:
        # Bot is disabled for this conversation - ignore message
        logger.info(
            f"Ignoring message for conversation {payload.conversation.id}: "
            f"atencion_automatica=false (bot disabled)",
            extra={
                "conversation_id": str(payload.conversation.id),
                "customer_phone": payload.sender.phone_number,
            }
        )
        return JSONResponse(
            status_code=200,
            content={"status": "ignored_auto_attention_disabled"}
        )

    elif atencion_automatica is None:
        # First message from this customer - enable bot and continue processing
        logger.info(
            f"First message for conversation {payload.conversation.id}: "
            f"setting atencion_automatica=true",
            extra={
                "conversation_id": str(payload.conversation.id),
                "customer_phone": payload.sender.phone_number,
            }
        )

        # Update conversation to enable bot
        try:
            chatwoot_client = ChatwootClient()
            await chatwoot_client.update_conversation_attributes(
                conversation_id=payload.conversation.id,
                attributes={"atencion_automatica": True}
            )
            logger.info(
                f"Successfully enabled bot for conversation {payload.conversation.id}"
            )
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

    # If atencion_automatica is True or was just set, continue processing normally
    logger.debug(
        f"Processing message for conversation {payload.conversation.id}: "
        f"atencion_automatica={atencion_automatica}",
        extra={
            "conversation_id": str(payload.conversation.id),
            "atencion_automatica": atencion_automatica,
        }
    )

    # Initialize message text and audio tracking fields
    message_text = last_message.content or ""
    is_audio_transcription = False
    audio_url = None

    # Check if message has audio attachments (attachments are in message.attachments)
    # Also check root-level attachments for backward compatibility
    message_attachments = last_message.attachments or payload.attachments
    if message_attachments:
        audio_attachments = [
            att for att in message_attachments
            if att.file_type == "audio"
        ]

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
                }
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
                        audio_data = await response.read()

                # 2. Save to temporary OGG file
                with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
                    temp_ogg.write(audio_data)
                    ogg_path = Path(temp_ogg.name)

                logger.debug(
                    f"Audio downloaded: {ogg_path.name}",
                    extra={
                        "conversation_id": str(payload.conversation.id),
                        "file_size_mb": len(audio_data) / (1024 * 1024),
                    }
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
                        }
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
                        }
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

    # Create message event for Redis
    message_event = ChatwootMessageEvent(
        conversation_id=str(payload.conversation.id),
        customer_phone=payload.sender.phone_number,  # Will be normalized to E.164
        message_text=message_text,
        customer_name=payload.sender.name,
        is_audio_transcription=is_audio_transcription,
        audio_url=audio_url,
    )

    logger.info(
        f"Parsed message event: conversation_id={message_event.conversation_id}, "
        f"phone={message_event.customer_phone}, name={message_event.customer_name}, "
        f"text='{message_event.message_text[:100]}'"
    )

    # Log full message content for debugging
    logger.debug(
        f"Full incoming message: '{message_event.message_text}'",
        extra={
            "conversation_id": message_event.conversation_id,
            "customer_phone": message_event.customer_phone,
            "message_length": len(message_event.message_text) if message_event.message_text else 0,
        }
    )

    # Publish to Redis channel
    await publish_to_channel(
        "incoming_messages",
        message_event.model_dump(),
    )

    # Log Redis payload for debugging
    logger.debug(
        f"Redis payload published: {message_event.model_dump()}",
        extra={"conversation_id": message_event.conversation_id}
    )

    logger.info(
        f"Chatwoot message enqueued: conversation_id={message_event.conversation_id}, "
        f"phone={message_event.customer_phone}"
    )

    return JSONResponse(status_code=200, content={"status": "received"})
