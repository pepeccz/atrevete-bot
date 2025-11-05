"""
LangGraph Agent Service Entry Point
Background worker for conversation orchestration
"""
import asyncio
import json
import logging
import signal
from datetime import UTC, datetime

from agent.graphs.conversation_flow import MAITE_SYSTEM_PROMPT, create_conversation_graph
from agent.state.checkpointer import get_redis_checkpointer, initialize_redis_indexes
from agent.state.helpers import add_message
from agent.utils.monitoring import get_langfuse_handler
from shared.logging_config import configure_logging
from shared.redis_client import get_redis_client, publish_to_channel

# Configure structured JSON logging
configure_logging()
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_event = asyncio.Event()


async def subscribe_to_incoming_messages():
    """
    Subscribe to incoming_messages Redis channel and process with LangGraph.

    This worker listens for messages published by the FastAPI webhook receiver,
    processes them through the conversation StateGraph, and publishes responses
    to the outgoing_messages channel.

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
    client = get_redis_client()

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

    logger.info("Subscribing to 'incoming_messages' channel...")

    # Subscribe to channel
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
                customer_name = data.get("customer_name")  # Get name from Chatwoot webhook

                logger.info(
                    f"Message received: conversation_id={conversation_id}, phone={customer_phone}, name={customer_name}",
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

                # Create initial ConversationState
                # NOTE: Only pass essential fields. LangGraph will load messages, total_message_count,
                # and other fields from the checkpoint (if thread_id exists in Redis).
                # Do NOT initialize messages/total_message_count here as it would overwrite the checkpoint.
                #
                # The graph's entry point will handle adding the new user message to the existing
                # conversation history loaded from the checkpoint.
                state = {
                    "conversation_id": conversation_id,
                    "customer_phone": customer_phone,
                    "customer_name": customer_name,  # Use name from webhook if available
                    "user_message": message_text,  # Store the incoming message for the graph to process
                    "updated_at": datetime.now(UTC),
                }

                # Create Langfuse handler for tracing and token monitoring
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
                    langfuse_handler = None

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
                    result = await graph.ainvoke(state, config=config)

                    # Flush Langfuse traces to ensure they're sent
                    if langfuse_handler:
                        try:
                            await langfuse_handler.flushAsync()
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

                    # Flush Langfuse traces even on error to capture error context
                    if langfuse_handler:
                        try:
                            await langfuse_handler.flushAsync()
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
                    continue

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
                        "ai_message_preview": ai_message[:50],
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

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in message: {e}")
                continue

            except Exception as e:
                logger.error(
                    f"Error processing message: {e}",
                    extra={
                        "conversation_id": data.get("conversation_id") if "data" in locals() else "unknown",
                    },
                    exc_info=True,
                )
                continue

    except asyncio.CancelledError:
        logger.info("Incoming message subscriber cancelled")
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
