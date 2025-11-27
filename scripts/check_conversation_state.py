#!/usr/bin/env python3
"""
Script to check the conversation state from Redis checkpoint.
"""

import asyncio
import sys
sys.path.append('/home/pepe/atrevete-bot')

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
import redis.asyncio as redis


async def check_state():
    """Check the conversation state from Redis."""
    # Connect to localhost Redis (not using docker network name)
    redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=False)
    checkpointer = AsyncRedisSaver(redis_client)

    # Get state for thread_id test-123
    config = {"configurable": {"thread_id": "test-123"}}

    try:
        checkpoint = await checkpointer.aget(config)

        if checkpoint:
            print("✅ Found checkpoint for conversation test-123")
            print("\n📊 Conversation State:")

            state = checkpoint.get("channel_values", {})

            # Print relevant fields
            print(f"   Customer Phone: {state.get('customer_phone')}")
            print(f"   Customer Name: {state.get('customer_name')}")
            print(f"   Customer ID: {state.get('customer_id')}")
            print(f"\n📨 Messages:")

            messages = state.get('messages', [])
            for i, msg in enumerate(messages, 1):
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                print(f"\n   Message {i} ({role}):")
                print(f"   {content}")
        else:
            print("❌ No checkpoint found for conversation test-123")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(check_state())
