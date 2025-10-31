#!/usr/bin/env python3
"""
Test pack suggestion (requires multiple tool calls: get_services + suggest_pack_tool).
"""

import asyncio
import json
import redis.asyncio as redis


async def send_pack_query():
    """Send a test message asking about mechas."""

    redis_client = redis.Redis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=True
    )

    message_payload = {
        "conversation_id": "test-pack-456",
        "customer_phone": "+34623226544",
        "message_text": "Quiero hacerme mechas",
        "customer_name": "Pepe"
    }

    print("📤 Sending mechas query (should suggest pack)...")
    print(f"   Query: '{message_payload['message_text']}'")

    await redis_client.publish(
        "incoming_messages",
        json.dumps(message_payload)
    )

    print("✅ Message published!")
    print("\n📋 Expected: Bot should suggest 'Mechas + Corte' pack")
    print("   (Requires get_services + suggest_pack_tool)")
    print("\n📊 Check: docker compose logs agent -f --tail 50")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(send_pack_query())
