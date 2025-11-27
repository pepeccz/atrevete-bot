#!/usr/bin/env python3
"""
Test script to simulate a WhatsApp message from Chatwoot webhook.
This script publishes a message to the 'incoming_messages' Redis channel
to test automatic customer identification.
"""

import asyncio
import json
import redis.asyncio as redis
import sys


async def send_test_message():
    """Send a test message simulating a WhatsApp message from Chatwoot."""

    # Connect to Redis
    redis_client = redis.Redis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=True
    )

    # Create message payload (simulating Chatwoot webhook format)
    message_payload = {
        "conversation_id": "test-123",
        "customer_phone": "+34623226544",
        "message_text": "Holaa",
        "customer_name": "Pepe"  # Name from Chatwoot contact
    }

    print("📤 Sending test message to Redis channel 'incoming_messages'...")
    print(f"   Payload: {json.dumps(message_payload, indent=2)}")

    # Publish to incoming_messages channel
    await redis_client.publish(
        "incoming_messages",
        json.dumps(message_payload)
    )

    print("✅ Message published successfully!")
    print("\n📋 What should happen:")
    print("   1. Agent receives message from Redis")
    print("   2. Agent creates initial state with customer_phone and customer_name")
    print("   3. Agent queries database for customer with phone +34623226544")
    print("   4. Agent finds 'Pepe' in database")
    print("   5. Bot should greet with: '¡Hola, Pepe! 😊 ¿En qué puedo ayudarte hoy?'")
    print("\n📊 Check logs with: docker compose logs agent -f")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(send_test_message())
