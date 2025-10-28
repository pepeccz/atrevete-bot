"""
LangGraph Agent Service Entry Point
Background worker for conversation orchestration
"""
import asyncio
import json
import logging
import signal
from datetime import UTC, datetime

from agent.graphs.conversation_flow import create_conversation_graph
from agent.state.checkpointer import get_redis_checkpointer
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
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    from shared.config import get_settings

    client = get_redis_client()
    settings = get_settings()

    logger.info(f"Initializing AsyncRedisSaver with URL: {settings.REDIS_URL}")

    # Create checkpointer using async context manager pattern
    async with AsyncRedisSaver.from_conn_string(settings.REDIS_URL) as checkpointer:
        logger.info("AsyncRedisSaver initialized successfully")

        graph = create_conversation_graph(checkpointer=checkpointer)

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

                    logger.info(
                        f"Message received: conversation_id={conversation_id}, phone={customer_phone}",
                        extra={
                            "conversation_id": conversation_id,
                            "customer_phone": customer_phone,
                        },
                    )

                    # Create initial ConversationState
                    state = {
                        "conversation_id": conversation_id,
                        "customer_phone": customer_phone,
                        "customer_name": None,
                        "messages": [{"role": "user", "content": message_text}],
                        "current_intent": None,
                        "metadata": {},
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                    }

                    # Invoke graph with checkpointing
                    config = {"configurable": {"thread_id": conversation_id}}
                    logger.info(
                        f"Invoking graph for thread_id={conversation_id}",
                        extra={"conversation_id": conversation_id},
                    )

                    result = await graph.ainvoke(state, config=config)

                    # Extract AI response from result state
                    ai_message = result["messages"][-1]["content"]

                    logger.info(
                        f"Graph completed for conversation_id={conversation_id}",
                        extra={
                            "conversation_id": conversation_id,
                            "ai_message_preview": ai_message[:50],
                        },
                    )

                    # Publish to outgoing_messages channel
                    await publish_to_channel(
                        "outgoing_messages",
                        {
                            "conversation_id": conversation_id,
                            "customer_phone": customer_phone,
                            "message": ai_message,
                        },
                    )

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
