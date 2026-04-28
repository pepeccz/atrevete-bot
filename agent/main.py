"""
LangGraph Agent Service Entry Point
Background worker for conversation orchestration
"""

import asyncio
import json
import logging
import os
import signal
import sys
from time import perf_counter
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.batching.message_batcher import MessageBatcher
from agent.checkpointer import get_checkpointer, setup_checkpointer
from agent.graph import create_graph
from agent.resume_handler import build_invoke_input
from agent.utils.monitoring import get_langfuse_client, get_langfuse_handler
from shared.config import get_settings
from shared.logging_config import configure_logging
from shared.redis_client import (
    CONSUMER_GROUP,
    INCOMING_STREAM,
    acknowledge_message,
    # Redis Streams functions
    create_consumer_group,
    get_redis_client,
    move_to_dead_letter,
    publish_to_channel,
    read_from_stream,
)
from shared.startup_validator import StartupValidationError, validate_startup_config

# Configure structured JSON logging
configure_logging()
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_event = asyncio.Event()

# Global batcher instance (initialized in subscribe_to_incoming_messages)
batcher: MessageBatcher | None = None

_PHONE_GUARD_REPLY = "No pude identificar tu número. Un compañero te contactará en breve."


# =============================================================================
# Telemetry helpers — pure functions, no side effects, easy to unit-test
# =============================================================================

_TOOL_RESULT_MAX_CHARS = 500


def _extract_tokens(messages: list[Any]) -> tuple[int | None, int | None]:
    """Extract token counts from the last AIMessage in *messages*.

    Returns (tokens_in, tokens_out). Both are None when usage_metadata is absent
    or when there is no AIMessage in the slice.

    Args:
        messages: Slice of LangChain messages for the current turn.

    Returns:
        Tuple (tokens_in, tokens_out) — either both ints or both None.
    """
    last_ai: AIMessage | None = None
    for msg in messages:
        if isinstance(msg, AIMessage):
            last_ai = msg
    if last_ai is None:
        return None, None
    meta = getattr(last_ai, "usage_metadata", None)
    if not meta:
        return None, None
    return meta.get("input_tokens"), meta.get("output_tokens")


def _extract_tool_calls(messages: list[Any]) -> list[dict] | None:
    """Build a compact tool-calls list from paired AIMessage.tool_calls + ToolMessages.

    For each tool_call in the slice's AIMessages, locates the matching ToolMessage
    by tool_call_id and stores a summary truncated to _TOOL_RESULT_MAX_CHARS chars.

    Returns None (not []) when no tool invocations are present.

    Args:
        messages: Slice of LangChain messages for the current turn.

    Returns:
        List of {name, args, result_summary} dicts, or None.
    """
    # Index ToolMessages by tool_call_id for O(1) lookup
    tool_results: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            tool_results[msg.tool_call_id] = content

    entries: list[dict] = []
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for tc in getattr(msg, "tool_calls", []) or []:
            call_id = tc.get("id") or tc.get("tool_call_id", "")
            raw_result = tool_results.get(call_id, "")
            entries.append(
                {
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                    "result_summary": raw_result[:_TOOL_RESULT_MAX_CHARS],
                }
            )

    return entries if entries else None


async def record_turn(
    conversation_history_id: UUID,
    latency_ms: int,
    messages_slice: list[Any],
) -> None:
    """Insert one ConversationTurn row for the completed agent turn.

    Best-effort: all exceptions are caught, logged at WARNING, and swallowed
    so telemetry failures never affect the user-visible agent response.

    Args:
        conversation_history_id: PK of the parent ConversationHistory row.
        latency_ms: Wall-clock time of graph.ainvoke() in milliseconds.
        messages_slice: New messages appended during this turn.
    """
    try:
        from sqlalchemy import func, select

        from database.connection import get_async_session
        from database.models import ConversationTurn

        tokens_in, tokens_out = _extract_tokens(messages_slice)
        tool_calls = _extract_tool_calls(messages_slice)

        async with get_async_session() as session:
            count_result = await session.execute(
                select(func.count()).select_from(ConversationTurn).where(
                    ConversationTurn.conversation_history_id == conversation_history_id
                )
            )
            existing_count: int = count_result.scalar() or 0
            turn_number = existing_count + 1

            session.add(
                ConversationTurn(
                    conversation_history_id=conversation_history_id,
                    turn_number=turn_number,
                    latency_ms=latency_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    tool_calls=tool_calls,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Telemetry record_turn failed (non-fatal) — %s: %s",
            type(exc).__name__,
            exc,
            extra={"conversation_history_id": str(conversation_history_id)},
        )


def _is_phone_empty(phone: str | None) -> bool:
    """Treat None, empty, and whitespace-only phone as empty."""
    return not (phone or "").strip()


async def _persist_assistant_message(conversation_id: str | None, content: str | None) -> None:
    """Insert an assistant ConversationMessage child row for live admin visibility.

    Idempotent: skips when an identical (role, content) row already exists for
    this conversation. Falls back silently if DB or parent row is unavailable.
    """
    if not conversation_id or not content:
        return

    from datetime import datetime, timezone
    from sqlalchemy import func, select

    from database.connection import get_async_session
    from database.models import ConversationHistory, ConversationMessage

    conv_id_str = str(conversation_id)

    async with get_async_session() as session:
        parent_result = await session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conv_id_str
            )
        )
        parent = parent_result.scalar_one_or_none()
        if parent is None:
            return  # Webhook hasn't created the parent yet — skip

        dup_result = await session.execute(
            select(ConversationMessage.id).where(
                ConversationMessage.conversation_history_id == parent.id,
                ConversationMessage.role == "assistant",
                ConversationMessage.content == content,
            )
        )
        if dup_result.scalar_one_or_none() is not None:
            return

        now = datetime.now(tz=timezone.utc)
        session.add(
            ConversationMessage(
                conversation_history_id=parent.id,
                role="assistant",
                content=content,
                created_at=now,
            )
        )
        await session.flush()

        count_result = await session.execute(
            select(func.count())
            .select_from(ConversationMessage)
            .where(ConversationMessage.conversation_history_id == parent.id)
        )
        parent.message_count = count_result.scalar() or 0
        parent.ended_at = now
        await session.commit()


async def _maybe_reject_empty_phone(conversation_id: str, customer_phone: str | None) -> bool:
    """Short-circuit batch processing when phone is missing.

    Returns True and sends a canned outgoing reply when phone is empty;
    returns False when phone is valid and the caller should continue.
    """
    if not _is_phone_empty(customer_phone):
        return False
    logger.warning(
        "Phone guard tripped — skipping graph invoke",
        extra={
            "event": "phone_guard_tripped",
            "conversation_id": conversation_id,
        },
    )
    await publish_to_channel(
        "outgoing_messages",
        {
            "conversation_id": conversation_id,
            "customer_phone": customer_phone or "",
            "message": _PHONE_GUARD_REPLY,
        },
    )
    return True


async def subscribe_to_incoming_messages():
    """
    Subscribe to incoming_messages Redis channel and process with LangGraph.

    This worker listens for messages published by the FastAPI webhook receiver,
    batches them within a configurable time window (default 30s), and processes
    batched messages through the conversation StateGraph.

    Message format (incoming_messages):
        {
            "conversation_id": "wa-msg-123",
            "customer_phone": "+34612345678",
            "message_text": "Hello"
        }

    Message format (outgoing_messages):
        {
            "conversation_id": "wa-msg-123",
            "customer_phone": "+34612345678",
            "message": "AI response text"
        }
    """
    global batcher

    # =========================================================================
    # STARTUP VALIDATION (Fase 4 - Config Validation)
    # =========================================================================
    # Validate critical configuration before initializing services.
    # This catches misconfigurations early (fail-fast) rather than at runtime.
    logger.info("Running startup configuration validation...")
    try:
        await validate_startup_config(require_google_calendar=False)
        logger.info("Startup configuration validation passed")
    except StartupValidationError as e:
        logger.critical(f"Startup blocked due to configuration errors: {e}")
        raise  # Re-raise to stop the service

    client = get_redis_client()
    settings = get_settings()

    logger.info("Initializing Redis checkpointer...")

    # NOTE: get_checkpointer() returns an async context manager.
    # The `async with` block below spans the entire consumer lifetime so
    # the Redis connection stays open.  graph is built inside the context
    # after asetup() has been called (idempotent index creation).
    #
    # store (AsyncRedisStore) is deferred post-MVP; graph accepts store=None.
    async with get_checkpointer(settings.REDIS_URL) as saver:
        await setup_checkpointer(saver)
        logger.info("AsyncRedisSaver ready — indexes created/verified")

        graph = create_graph(checkpointer=saver)
        logger.info("Authoritative v7 conversation graph created successfully")

        # Initialize message batcher with configurable window and Redis for crash recovery
        batch_window = settings.MESSAGE_BATCH_WINDOW_SECONDS
        batcher = MessageBatcher(window_seconds=batch_window, redis_client=client)
        logger.info(
            f"Message batcher initialized | window_seconds={batch_window} | "
            f"batching={'enabled' if batch_window > 0 else 'disabled'} | "
            f"redis_persistence=enabled"
        )

        async def process_batch(conversation_id: str, messages: list[dict]) -> None:
            """
            Process a batch of messages as one combined input.

            This callback is invoked by the MessageBatcher when the batch window expires.
            All messages in the batch are combined into a single user_message.

            Args:
                conversation_id: The conversation thread ID
                messages: List of message dicts from the batch
            """
            # Combine all message texts with double newline separator
            combined_text = "\n\n".join(
                [msg.get("message_text", "") for msg in messages if msg.get("message_text")]
            )

            # Use metadata from last message (most recent)
            last_msg = messages[-1]
            customer_phone = last_msg.get("customer_phone")
            # Prefer sender_name (new field) over customer_name (deprecated)
            sender_name = last_msg.get("sender_name") or last_msg.get("customer_name")

            # Pre-graph phone guard: reject empty/whitespace phone before invoke.
            if await _maybe_reject_empty_phone(conversation_id, customer_phone):
                return

            # Check if any message was from audio transcription
            has_audio = any(msg.get("is_audio_transcription") for msg in messages)

            logger.info(
                f"Processing batch | conversation_id={conversation_id} | "
                f"messages={len(messages)} | combined_length={len(combined_text)} | "
                f"has_audio={has_audio}",
                extra={
                    "conversation_id": conversation_id,
                    "batch_size": len(messages),
                    "has_audio": has_audio,
                },
            )

            # Log full combined message for debugging
            logger.debug(
                f"Full combined message: '{combined_text}'",
                extra={
                    "conversation_id": conversation_id,
                    "message_length": len(combined_text),
                },
            )

            # Truncate incoming message to avoid context overflow
            truncated_text = combined_text[:2000] if combined_text else ""

            # Create runtime state seed for the create_agent graph.
            # `sender_name` from Chatwoot webhook is stored in `pending_whatsapp_name`
            # for silent customer creation (name is never mentioned in bot responses).
            state = {
                "conversation_id": conversation_id,
                "customer_phone": customer_phone or "",
                "user_message": truncated_text,
                "pending_whatsapp_name": sender_name,
                "messages": [HumanMessage(content=truncated_text)] if truncated_text else [],
            }

            # Create Langfuse handler for tracing and token monitoring
            langfuse_handler = None
            langfuse_client = None
            try:
                langfuse_handler = get_langfuse_handler(
                    conversation_id=conversation_id,
                    customer_phone=customer_phone,
                    customer_name=sender_name,
                )
                langfuse_client = get_langfuse_client()
            except Exception as langfuse_error:
                logger.warning(
                    f"Failed to create Langfuse handler (continuing without tracing): {langfuse_error}",
                    extra={"conversation_id": conversation_id},
                )

            # Invoke graph with checkpointing and Langfuse callbacks
            config = {
                "configurable": {"thread_id": f"v2:{conversation_id}"},
                "callbacks": [langfuse_handler] if langfuse_handler else [],
            }
            logger.info(
                f"Invoking graph for thread_id={conversation_id}",
                extra={"conversation_id": conversation_id},
            )

            # Capture message count BEFORE graph invocation for freshness guard
            messages_before = len(state.get("messages", []))

            try:
                # ================================================================
                # INTERRUPT RESUME DETECTION (Phase 7)
                # ================================================================
                # If the graph is paused at await_confirmation, resume with
                # Command(resume=combined_text) instead of a fresh state dict.
                invoke_payload, was_interrupted = await build_invoke_input(
                    graph, config, combined_text, state
                )
                if was_interrupted:
                    logger.info(
                        f"Resuming interrupted graph (await_confirmation) | "
                        f"conversation_id={conversation_id}",
                        extra={"conversation_id": conversation_id},
                    )

                # ================================================================
                # GRAPH INVOCATION WITH CHECKPOINT FLUSH (ADR-010)
                # ================================================================
                _t0 = perf_counter()
                result = await graph.ainvoke(invoke_payload, config=config)
                _latency_ms = int((perf_counter() - _t0) * 1000)

                # ================================================================
                # CHECKPOINT PERSISTENCE (ADR-011: Single Source of Truth)
                # ================================================================
                logger.debug(
                    f"Checkpoint persisted (FSM consolidated) | conversation_id={conversation_id}",
                    extra={"conversation_id": conversation_id},
                )

                # Flush Langfuse traces to ensure they're sent
                if langfuse_client:
                    try:
                        langfuse_client.flush()
                        logger.debug(
                            f"Langfuse traces flushed for conversation_id={conversation_id}"
                        )
                    except Exception as flush_error:
                        logger.warning(
                            f"Failed to flush Langfuse traces (trace may be incomplete): {flush_error}",
                            extra={"conversation_id": conversation_id},
                        )

            except Exception as graph_error:
                # Handle checkpoint corruption or graph execution errors
                logger.error(
                    f"Graph invocation failed for conversation_id={conversation_id}: {graph_error}",
                    extra={
                        "conversation_id": conversation_id,
                        "error_type": type(graph_error).__name__,
                    },
                    exc_info=True,
                )

                # Flush Langfuse traces even on error
                if langfuse_client:
                    try:
                        langfuse_client.flush()
                    except Exception as flush_error:
                        logger.warning(f"Failed to flush Langfuse traces on error: {flush_error}")

                # Send fallback error message to user
                fallback_message = (
                    "Lo siento, tuve un problema técnico. ¿Puedes intentarlo de nuevo? 💕"
                )
                await publish_to_channel(
                    "outgoing_messages",
                    {
                        "conversation_id": conversation_id,
                        "customer_phone": customer_phone,
                        "message": fallback_message,
                    },
                )
                logger.info(f"Sent fallback message for conversation_id={conversation_id}")
                return

            # ================================================================
            # TELEMETRY CAPTURE (best-effort, never blocks response)
            # ================================================================
            try:
                from sqlalchemy import select as _sa_select

                from database.connection import get_async_session as _get_session
                from database.models import ConversationHistory as _CH

                async with _get_session() as _tel_session:
                    _ch_result = await _tel_session.execute(
                        _sa_select(_CH.id).where(_CH.conversation_id == conversation_id)
                    )
                    _ch_id = _ch_result.scalar_one_or_none()

                if _ch_id is not None:
                    _result_messages = result.get("messages", [])
                    _messages_slice = _result_messages[messages_before:]
                    await record_turn(
                        conversation_history_id=_ch_id,
                        latency_ms=_latency_ms,
                        messages_slice=_messages_slice,
                    )
            except Exception as _tel_exc:  # noqa: BLE001
                logger.warning(
                    "Telemetry capture failed (non-fatal): %s",
                    _tel_exc,
                    extra={"conversation_id": conversation_id},
                )

            # ================================================================
            # PUBLISH FRESHNESS GUARD (T1.1)
            # ================================================================
            # Only publish a message produced in THIS turn:
            # (a) result["messages"] must have grown beyond messages_before
            # (b) the last message role must be "assistant"
            # If either check fails, send a Spanish fallback instead.
            result_messages = result.get("messages", [])
            messages_after = len(result_messages)
            last_message = result_messages[-1] if result_messages else None

            # Determine role of the last message (support dicts and LangChain BaseMessage)
            if last_message is not None:
                if isinstance(last_message, dict):
                    last_role = last_message.get("role") or last_message.get("type")
                else:
                    last_role = getattr(last_message, "type", None) or getattr(
                        last_message, "role", None
                    )
            else:
                last_role = None

            freshness_ok = (messages_after > messages_before) and (last_role in ("assistant", "ai"))

            if not freshness_ok:
                logger.warning(
                    f"Publish freshness guard triggered | conversation_id={conversation_id} | "
                    f"messages_before={messages_before} | messages_after={messages_after} | "
                    f"last_role={last_role}",
                    extra={"conversation_id": conversation_id},
                )
                ai_message = (
                    "Perdón, tuve un problema al responder. "
                    "Ya lo reviso y te pido que me escribas de nuevo en un momento."
                )
            else:
                # Extract AI response from result state
                # Handle both dict and Message object formats
                if isinstance(last_message, dict):
                    content = last_message.get("content", "")
                else:
                    content = last_message.content  # type: ignore[union-attr]

                # Extract text from content (handle both string and list of blocks)
                if isinstance(content, str):
                    ai_message = content
                elif isinstance(content, list):
                    # Content is a list of blocks (text + tool_use) - extract only text blocks
                    text_blocks = [
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    ai_message = " ".join(text_blocks).strip()
                else:
                    ai_message = str(content)

            # Log full AI response for debugging
            logger.debug(
                f"Full AI response: '{ai_message}'",
                extra={
                    "conversation_id": conversation_id,
                    "response_length": len(ai_message) if ai_message else 0,
                },
            )

            logger.info(
                f"Graph completed for conversation_id={conversation_id}",
                extra={
                    "conversation_id": conversation_id,
                    "ai_message_preview": ai_message[:50] if ai_message else "",
                },
            )

            # Prepare outgoing message payload
            outgoing_payload = {
                "conversation_id": conversation_id,
                "customer_phone": customer_phone,
                "message": ai_message,
            }

            # Log full outgoing payload for debugging
            logger.debug(
                f"Outgoing Redis payload: {outgoing_payload}",
                extra={"conversation_id": conversation_id},
            )

            # Publish to outgoing_messages channel
            await publish_to_channel("outgoing_messages", outgoing_payload)

            logger.info(
                f"Message published to outgoing_messages: conversation_id={conversation_id}",
                extra={"conversation_id": conversation_id},
            )

            # ================================================================
            # ACK STREAM MESSAGES (Redis Streams only)
            # ================================================================
            # After successful processing, acknowledge all stream messages in the batch
            # This removes them from the pending list (they won't be redelivered)
            if settings.USE_REDIS_STREAMS:
                stream_msg_ids = [
                    msg.get("_stream_msg_id") for msg in messages if msg.get("_stream_msg_id")
                ]
                for stream_msg_id in stream_msg_ids:
                    try:
                        await acknowledge_message(INCOMING_STREAM, CONSUMER_GROUP, stream_msg_id)
                        logger.debug(
                            f"ACK stream message {stream_msg_id} | conversation_id={conversation_id}"
                        )
                    except Exception as ack_error:
                        logger.warning(
                            f"Failed to ACK message {stream_msg_id}: {ack_error}",
                            extra={"conversation_id": conversation_id},
                        )

        # Set the callback for when batches expire
        batcher.set_callback(process_batch)

        # =========================================================================
        # BATCH RECOVERY (Phase 6 - Crash Recovery)
        # =========================================================================
        # Recover any pending batches from a previous crash
        recovered_count = await batcher.recover_pending_batches()
        if recovered_count > 0:
            logger.info(f"Recovered {recovered_count} pending message batches from Redis")

        # ========================================================================
        # MESSAGE SUBSCRIPTION (Redis Streams or Pub/Sub based on config)
        # ========================================================================

        if settings.USE_REDIS_STREAMS:
            # ====================================================================
            # REDIS STREAMS MODE: Persistent with acknowledgment
            # ====================================================================
            consumer_name = f"agent-{os.getpid()}"

            logger.info(
                f"Initializing Redis Streams consumer | stream={INCOMING_STREAM} | "
                f"group={CONSUMER_GROUP} | consumer={consumer_name}"
            )

            # Create consumer group if it doesn't exist
            await create_consumer_group(INCOMING_STREAM, CONSUMER_GROUP)

            logger.info(
                f"Redis Streams consumer ready | stream={INCOMING_STREAM} | "
                f"consumer={consumer_name}"
            )

            try:
                while not shutdown_event.is_set():
                    try:
                        # Read messages from stream (blocks for 5 seconds if no messages)
                        messages = await read_from_stream(
                            INCOMING_STREAM,
                            CONSUMER_GROUP,
                            consumer_name,
                            count=10,  # Process up to 10 messages at a time
                            block_ms=5000,  # 5 second block
                        )

                        for stream_msg_id, data in messages:
                            try:
                                conversation_id = data.get("conversation_id")
                                customer_phone = data.get("customer_phone")
                                message_text = data.get("message_text")
                                # sender_name is the new field; customer_name kept for rolling deploys
                                _ = data.get("sender_name") or data.get("customer_name")

                                logger.info(
                                    f"Stream message received: conversation_id={conversation_id}, "
                                    f"phone={customer_phone}, stream_msg_id={stream_msg_id}",
                                    extra={
                                        "conversation_id": conversation_id,
                                        "customer_phone": customer_phone,
                                        "stream_msg_id": stream_msg_id,
                                    },
                                )

                                # Log full incoming message for debugging
                                logger.debug(
                                    f"Full incoming message: '{message_text}'",
                                    extra={
                                        "conversation_id": conversation_id,
                                        "message_length": len(message_text) if message_text else 0,
                                    },
                                )

                                # Add stream_msg_id to message data for ACK after processing
                                data["_stream_msg_id"] = stream_msg_id

                                # Add message to batcher (will be processed after window expires)
                                await batcher.add_message(
                                    conversation_id=conversation_id,
                                    message_data=data,
                                )

                            except Exception as e:
                                logger.error(
                                    f"Error processing stream message {stream_msg_id}: {e}",
                                    exc_info=True,
                                )
                                # Move to dead letter queue for later inspection
                                try:
                                    await move_to_dead_letter(
                                        INCOMING_STREAM,
                                        CONSUMER_GROUP,
                                        stream_msg_id,
                                        data,
                                        str(e),
                                    )
                                except Exception as dlq_error:
                                    logger.error(f"Failed to move to DLQ: {dlq_error}")
                                continue

                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.error(f"Error reading from stream: {e}", exc_info=True)
                        # Brief backoff on error before retrying
                        await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info("Stream consumer cancelled")
                if batcher:
                    logger.info("Flushing pending batches before shutdown...")
                    await batcher.flush_all()
                raise

            except Exception as e:
                logger.error(f"Fatal error in stream consumer: {e}", exc_info=True)
                raise

        else:
            # ====================================================================
            # LEGACY PUB/SUB MODE: Fire-and-forget (backward compatibility)
            # ====================================================================
            logger.info("Subscribing to 'incoming_messages' channel (pub/sub mode)...")

            pubsub = client.pubsub()
            await pubsub.subscribe("incoming_messages")

            logger.info("Subscribed to 'incoming_messages' channel")

            try:
                async for message in pubsub.listen():
                    # Skip subscription confirmation messages
                    if message["type"] != "message":
                        continue

                    try:
                        # Parse message JSON
                        data = json.loads(message["data"])
                        conversation_id = data.get("conversation_id")
                        customer_phone = data.get("customer_phone")
                        message_text = data.get("message_text")
                        # sender_name is the new field; customer_name kept for rolling deploys
                        _ = data.get("sender_name") or data.get("customer_name")

                        logger.info(
                            f"Message received: conversation_id={conversation_id}, "
                            f"phone={customer_phone}",
                            extra={
                                "conversation_id": conversation_id,
                                "customer_phone": customer_phone,
                            },
                        )

                        # Log full incoming message for debugging
                        logger.debug(
                            f"Full incoming message: '{message_text}'",
                            extra={
                                "conversation_id": conversation_id,
                                "message_length": len(message_text) if message_text else 0,
                            },
                        )

                        # Add message to batcher (will be processed after window expires)
                        await batcher.add_message(
                            conversation_id=conversation_id,
                            message_data=data,
                        )

                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in message: {e}")
                        continue

                    except Exception as e:
                        logger.error(
                            f"Error adding message to batch: {e}",
                            extra={
                                "conversation_id": (
                                    data.get("conversation_id") if "data" in locals() else "unknown"
                                ),
                            },
                            exc_info=True,
                        )
                        continue

            except asyncio.CancelledError:
                logger.info("Incoming message subscriber cancelled")
                # Flush pending batches before shutting down
                if batcher:
                    logger.info("Flushing pending batches before shutdown...")
                    await batcher.flush_all()
                await pubsub.unsubscribe("incoming_messages")
                await pubsub.close()
                raise

            except Exception as e:
                logger.error(f"Fatal error in incoming message subscriber: {e}", exc_info=True)
                raise


async def subscribe_to_outgoing_messages():
    """
    Subscribe to outgoing_messages Redis channel and send via Chatwoot.

    This worker listens for messages published by the conversation graph,
    and sends them to customers via the Chatwoot API.

    Message format (outgoing_messages):
        {
            "conversation_id": "wa-msg-123",
            "customer_phone": "+34612345678",
            "message": "AI response text"
        }
    """
    # TODO Phase 7: move ChatwootClient to shared/ or agent/services/; agent/tools/ deleted
    from shared.chatwoot_client import ChatwootClient  # type: ignore[import]

    client = get_redis_client()
    chatwoot = ChatwootClient()

    logger.info("Subscribing to 'outgoing_messages' channel...")

    # Subscribe to channel
    pubsub = client.pubsub()
    await pubsub.subscribe("outgoing_messages")

    logger.info("Subscribed to 'outgoing_messages' channel")

    try:
        async for message in pubsub.listen():
            # Skip subscription confirmation messages
            if message["type"] != "message":
                continue

            try:
                # Parse message JSON
                data = json.loads(message["data"])
                customer_phone = data.get("customer_phone")
                message_text = data.get("message")
                conversation_id = data.get("conversation_id")

                logger.info(
                    f"Outgoing message received: conversation_id={conversation_id}, phone={customer_phone}",
                    extra={
                        "conversation_id": conversation_id,
                        "customer_phone": customer_phone,
                    },
                )

                # Log full outgoing message for debugging
                logger.debug(
                    f"Full outgoing message to Chatwoot: '{message_text}'",
                    extra={
                        "conversation_id": conversation_id,
                        "customer_phone": customer_phone,
                        "message_length": len(message_text) if message_text else 0,
                    },
                )

                # Send message via Chatwoot
                success = await chatwoot.send_message(
                    customer_phone, message_text, conversation_id=conversation_id
                )

                if success:
                    logger.info(
                        f"Message sent to {customer_phone}: success=True",
                        extra={
                            "conversation_id": conversation_id,
                            "customer_phone": customer_phone,
                        },
                    )
                    try:
                        await _persist_assistant_message(
                            conversation_id=conversation_id,
                            content=message_text,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to persist assistant message for {conversation_id}: {e}",
                            extra={"conversation_id": conversation_id},
                        )
                else:
                    logger.error(
                        f"Message sent to {customer_phone}: success=False",
                        extra={
                            "conversation_id": conversation_id,
                            "customer_phone": customer_phone,
                        },
                    )

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in outgoing message: {e}")
                continue

            except Exception as e:
                logger.error(
                    f"Error sending outgoing message: {e}",
                    extra={
                        "conversation_id": (
                            data.get("conversation_id") if "data" in locals() else "unknown"
                        ),
                    },
                    exc_info=True,
                )
                continue

    except asyncio.CancelledError:
        logger.info("Outgoing message subscriber cancelled")
        await pubsub.unsubscribe("outgoing_messages")
        await pubsub.close()
        raise

    except Exception as e:
        logger.error(f"Fatal error in outgoing message subscriber: {e}", exc_info=True)
        raise


def _make_task_done_callback(task_name: str):
    """
    Returns a done-callback that logs immediately when a task dies unexpectedly.

    This fires the moment the task finishes — even before the watchdog loop
    checks — so the error always appears in the logs regardless of timing.
    """

    def _on_done(task: asyncio.Task) -> None:
        if task.cancelled():
            # Normal shutdown path — not an error
            logger.info(f"Task '{task_name}' was cancelled (expected during shutdown)")
            return
        exc = task.exception()
        if exc is not None:
            logger.critical(
                f"Task '{task_name}' died with unhandled exception: {exc}",
                exc_info=exc,
            )

    return _on_done


async def _watchdog(
    tasks: dict[str, asyncio.Task],
    interval_seconds: float = 5.0,
) -> None:
    """
    Periodically checks that all critical tasks are still alive.

    If any task finishes unexpectedly (not cancelled), logs CRITICAL and
    triggers graceful shutdown so Docker/compose can restart the container.

    The done-callback on each task already logs the exception immediately;
    this watchdog is the enforcement mechanism that actually stops the process.
    """
    logger.info(
        f"Watchdog started | monitoring={list(tasks.keys())} | " f"interval={interval_seconds}s"
    )
    while not shutdown_event.is_set():
        await asyncio.sleep(interval_seconds)
        for name, task in tasks.items():
            if task.done() and not task.cancelled():
                exc = task.exception()
                logger.critical(
                    f"Watchdog detected dead task '{name}' "
                    f"(exception={type(exc).__name__ if exc else 'None'}). "
                    f"Exiting with code 1 so Docker restarts the container.",
                    exc_info=exc,
                )
                # Exit immediately with non-zero code so Docker/compose
                # restart_policy triggers a clean container restart.
                sys.exit(1)


async def main():
    """Agent worker main entry point"""
    logger.info("Agent service started")

    # Get the current event loop for signal handling
    loop = asyncio.get_running_loop()

    # Define signal handler that works with asyncio
    def handle_shutdown_signal():
        """Handle shutdown signals gracefully in async context"""
        logger.info("Received shutdown signal, initiating graceful shutdown...")
        shutdown_event.set()

    # Register signal handlers using loop.add_signal_handler (Unix only)
    try:
        loop.add_signal_handler(signal.SIGTERM, handle_shutdown_signal)
        loop.add_signal_handler(signal.SIGINT, handle_shutdown_signal)
        logger.info("Signal handlers registered")
    except NotImplementedError:
        # Windows doesn't support add_signal_handler, fallback to basic handling
        logger.warning("Signal handlers not supported on this platform")

    # Start both workers concurrently
    incoming_task = asyncio.create_task(subscribe_to_incoming_messages(), name="incoming_messages")
    outgoing_task = asyncio.create_task(subscribe_to_outgoing_messages(), name="outgoing_messages")

    # Attach done-callbacks so errors are logged THE MOMENT a task dies,
    # before the watchdog's next polling cycle fires.
    incoming_task.add_done_callback(_make_task_done_callback("incoming_messages"))
    outgoing_task.add_done_callback(_make_task_done_callback("outgoing_messages"))

    # Start watchdog that monitors task health every 5 seconds
    critical_tasks = {
        "incoming_messages": incoming_task,
        "outgoing_messages": outgoing_task,
    }
    watchdog_task = asyncio.create_task(
        _watchdog(critical_tasks, interval_seconds=5.0), name="watchdog"
    )

    try:
        # Wait for shutdown signal (set by signal handler OR watchdog)
        await shutdown_event.wait()
    except asyncio.CancelledError:
        logger.info("Main loop cancelled")
    finally:
        logger.info("Shutting down agent service...")
        watchdog_task.cancel()
        incoming_task.cancel()
        outgoing_task.cancel()
        try:
            await asyncio.gather(
                watchdog_task, incoming_task, outgoing_task, return_exceptions=True
            )
        except asyncio.CancelledError:
            pass
        logger.info("Agent service stopped")


if __name__ == "__main__":
    logger.info("Starting Atrévete Bot Agent Service")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("Agent service exited")
