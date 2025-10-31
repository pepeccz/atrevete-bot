#!/usr/bin/env python3
"""
Test script to verify tool execution works for price queries.
Simulates: "¿Cuánto cuesta el corte de pelo?"
"""

import asyncio
import json
import redis.asyncio as redis


async def send_price_query():
    """Send a test price query message."""

    redis_client = redis.Redis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=True
    )

    # Create message payload for price query
    message_payload = {
        "conversation_id": "test-price-123",
        "customer_phone": "+34623226544",
        "message_text": "¿Cuánto cuesta el corte de pelo?",
        "customer_name": "Pepe"
    }

    print("📤 Sending price query to Redis channel 'incoming_messages'...")
    print(f"   Query: '{message_payload['message_text']}'")
    print(f"   Customer: {message_payload['customer_name']}")

    # Publish to incoming_messages channel
    await redis_client.publish(
        "incoming_messages",
        json.dumps(message_payload)
    )

    print("✅ Message published successfully!")
    print("\n📋 Expected behavior with ReAct loop:")
    print("   1. Agent receives message")
    print("   2. LLM decides to call get_services tool")
    print("   3. Tool executes and returns service list with prices")
    print("   4. LLM receives tool result")
    print("   5. LLM generates final response with actual price")
    print("   6. User receives: 'El corte de pelo cuesta 25€ 💇'")
    print("\n📊 Check logs with: docker compose logs agent -f --tail 50")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(send_price_query())
