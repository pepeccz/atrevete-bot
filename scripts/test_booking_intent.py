#!/usr/bin/env python3
"""
Test script to verify Claude detects booking intent and calls start_booking_flow().
"""

import asyncio
import json
import redis.asyncio as redis


async def send_booking_intent_message():
    """Send a test message with clear booking intent."""

    redis_client = redis.Redis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=True
    )

    message_payload = {
        "conversation_id": "test-booking-intent-789",
        "customer_phone": "+34623226544",
        "message_text": "Perfecto, quiero reservar mechas y corte para el viernes",
        "customer_name": "Pepe"
    }

    print("📤 Sending booking intent message...")
    print(f"   Message: '{message_payload['message_text']}'")
    print()
    print("🎯 Expected behavior:")
    print("   1. Claude detects clear booking intent")
    print("   2. Claude calls start_booking_flow()")
    print("      - services: ['mechas', 'corte']")
    print("      - preferred_date: 'viernes'")
    print("   3. System sets booking_intent_confirmed = True")
    print("   4. Flow transitions to Tier 2 (transactional)")
    print()

    await redis_client.publish(
        "incoming_messages",
        json.dumps(message_payload)
    )

    print("✅ Message published!")
    print("\n📊 Monitor logs with:")
    print("   docker compose logs agent -f --tail 50 | grep -E '(start_booking_flow|Booking intent)'")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(send_booking_intent_message())
