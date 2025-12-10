"""
LangGraph Agent Service Entry Point
Background worker for conversation orchestration
"""
import asyncio
import json
import logging
import os
import signal
from datetime import UTC, datetime

from agent.batching.message_batcher import MessageBatcher
from agent.graphs.conversation_flow import MAITE_SYSTEM_PROMPT, create_conversation_graph
from agent.state.checkpointer import get_redis_checkpointer, initialize_redis_indexes
from agent.state.helpers import add_message
from agent.utils.monitoring import get_langfuse_handler
from shared.config import get_settings
from shared.logging_config import configure_logging
from shared.startup_validator import StartupValidationError, validate_startup_config
from shared.redis_client import (
    get_redis_client,
    publish_to_channel,
    # Redis Streams functions
    create_consumer_group,
    read_from_stream,
    acknowledge_message,
    move_to_dead_letter,
    INCOMING_STREAM,
    CONSUMER_GROUP,
)

# Configure structured JSON logging
configure_logging()
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_event = asyncio.Event()

# Global batcher instance (initialized in subscribe_to_incoming_messages)
batcher: MessageBatcher | None = None


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
        await validate_startup_config()
        logger.info("Startup configuration validation passed")
    except StartupValidationError as e:
        logger.critical(f"Startup blocked due to configuration errors: {e}")
        raise  # Re-raise to stop the service

    client = get_redis_client()
    settings = get_settings()

    logger.info("Initializing Redis checkpointer...")

    # Create checkpointer using get_redis_checkpointer() (simpler than async context manager)
    checkpointer = get_redis_checkpointer()

    # Initialize Redis indexes for LangGraph (creates checkpoint_writes, etc.)
    try:
        await initialize_redis_indexes(checkpointer)
        logger.info("Redis checkpointer initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Redis indexes: {e}")
        raise

    graph = create_conversation_graph(checkpointer=checkpointer)
    logger.info("Conversation graph created successfully")

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
        combined_text = "\n\n".join([
            msg.get("message_text", "") for msg in messages
            if msg.get("message_text")
        ])

        # Use metadata from last message (most recent)
        last_msg = messages[-1]
        customer_phone = last_msg.get("customer_phone")
        customer_name = last_msg.get("customer_name")

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
            }
        )

        # Log full combined message for debugging
        logger.debug(
            f"Full combined message: '{combined_text}'",
            extra={
                "conversation_id": conversation_id,
                "message_length": len(combined_text),
            }
        )

        # Create initial ConversationState
        # NOTE: Only pass essential fields. LangGraph will load messages, total_message_count,
        # and other fields from the checkpoint (if thread_id exists in Redis).
        state = {
            "conversation_id": conversation_id,
            "customer_phone": customer_phone,
            "customer_name": customer_name,
            "user_message": combined_text,
            "updated_at": datetime.now(UTC),
        }

        # Create Langfuse handler for tracing and token monitoring
        langfuse_handler = None
        try:
            langfuse_handler = get_langfuse_handler(
                conversation_id=conversation_id,
                customer_phone=customer_phone,
                customer_name=customer_name,
            )
        except Exception as langfuse_error:
            logger.warning(
                f"Failed to create Langfuse handler (continuing without tracing): {langfuse_error}",
                extra={"conversation_id": conversation_id},
            )

        # Invoke graph with checkpointing and Langfuse callbacks
        config = {
            "configurable": {"thread_id": conversation_id},
            "callbacks": [langfuse_handler] if langfuse_handler else [],
        }
        logger.info(
            f"Invoking graph for thread_id={conversation_id}",
            extra={"conversation_id": conversation_id},
        )

        try:
            # ================================================================
            # GRAPH INVOCATION WITH CHECKPOINT FLUSH (ADR-010)
            # ================================================================
            result = await graph.ainvoke(state, config=config)

            # ================================================================
            # CHECKPOINT PERSISTENCE (ADR-011: Single Source of Truth)
            # ================================================================
            logger.debug(
                f"Checkpoint persisted (FSM consolidated) | conversation_id={conversation_id}",
                extra={"conversation_id": conversation_id}
            )

            # Flush Langfuse traces to ensure they're sent
            if langfuse_handler:
                try:
                    langfuse_handler.flush()
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
            if langfuse_handler:
                try:
                    langfuse_handler.flush()
                except Exception as flush_error:
                    logger.warning(f"Failed to flush Langfuse traces on error: {flush_error}")

            # Send fallback error message to user
            fallback_message = "Lo siento, tuve un problema técnico. ¿Puedes intentarlo de nuevo? 💕"
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

        # Extract AI response from result state
        last_message = result["messages"][-1]

        # Handle both dict and Message object formats
        if isinstance(last_message, dict):
            content = last_message.get("content", "")
        else:
            content = last_message.content

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
            }
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
            extra={"conversation_id": conversation_id}
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
                msg.get("_stream_msg_id") for msg in messages
                if msg.get("_stream_msg_id")
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
                            customer_name = data.get("customer_name")

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
                                }
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
                    customer_name = data.get("customer_name")

                    logger.info(
                        f"Message received: conversation_id={conversation_id}, "
                        f"phone={customer_phone}, name={customer_name}",
                        extra={
                            "conversation_id": conversation_id,
                            "customer_phone": customer_phone,
                            "customer_name": customer_name,
                        },
                    )

                    # Log full incoming message for debugging
                    logger.debug(
                        f"Full incoming message: '{message_text}'",
                        extra={
                            "conversation_id": conversation_id,
                            "message_length": len(message_text) if message_text else 0,
                        }
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
                            "conversation_id": data.get("conversation_id") if "data" in locals() else "unknown",
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
    from agent.tools.notification_tools import ChatwootClient

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
                    }
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
                        "conversation_id": data.get("conversation_id") if "data" in locals() else "unknown",
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
    incoming_task = asyncio.create_task(subscribe_to_incoming_messages())
    outgoing_task = asyncio.create_task(subscribe_to_outgoing_messages())

    try:
        # Wait for shutdown signal
        await shutdown_event.wait()
    except asyncio.CancelledError:
        logger.info("Main loop cancelled")
    finally:
        logger.info("Shutting down agent service...")
        incoming_task.cancel()
        outgoing_task.cancel()
        try:
            await asyncio.gather(incoming_task, outgoing_task, return_exceptions=True)
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
