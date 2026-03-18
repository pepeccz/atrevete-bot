"""Redis-based harness for conversational QA flows."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from shared.config import get_settings
from shared.redis_client import INCOMING_STREAM


class RedisTestHarness:
    """Inject messages into the incoming stream and capture outgoing responses."""

    def __init__(
        self,
        redis_client: redis.Redis,
        binary_redis_client: redis.Redis | None = None,
        response_channel: str = "outgoing_messages",
    ):
        self.redis = redis_client
        self.binary_redis = binary_redis_client
        self.response_channel = response_channel
        self._pubsub: redis.client.PubSub | None = None
        self._owns_binary_client = binary_redis_client is None
        self._turn_counters: dict[str, int] = {}

    async def prepare_response_capture(self) -> None:
        if self._pubsub is None:
            self._pubsub = self.redis.pubsub()
            await self._pubsub.subscribe(self.response_channel)

    async def inject_message(
        self,
        conversation_id: str,
        message_text: str,
        customer_phone: str = "+34600000000",
        sender_name: str = "QA Test Client",
        customer_name: str | None = None,
    ) -> str:
        payload = {
            "conversation_id": conversation_id,
            "customer_phone": customer_phone,
            "message_text": message_text,
            "sender_name": sender_name,
            "customer_name": customer_name or sender_name,
            "is_audio_transcription": False,
            "audio_url": None,
        }
        return await self.redis.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

    async def capture_response(self, conversation_id: str, timeout: float = 30.0) -> dict[str, Any]:
        await self.prepare_response_capture()
        assert self._pubsub is not None

        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(
                    f"No response received on '{self.response_channel}' for conversation "
                    f"{conversation_id} within {timeout:.1f}s"
                )

            raw_message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=remaining)
            if raw_message is None:
                continue

            raw_data = raw_message.get("data")
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")
            payload = json.loads(raw_data)
            if payload.get("conversation_id") != conversation_id:
                continue

            return {
                "conversation_id": conversation_id,
                "customer_phone": payload.get("customer_phone"),
                "message": payload.get("message"),
                "timestamp_captured": datetime.now(UTC).isoformat(),
                "raw_payload": payload,
            }

    async def execute_turn(
        self,
        conversation_id: str,
        user_message: str,
        persona_name: str = "QA Test Client",
        timeout: float = 30.0,
        customer_phone: str = "+34600000000",
    ) -> dict[str, Any]:
        await self.prepare_response_capture()
        timestamp_sent = datetime.now(UTC).isoformat()
        await self.inject_message(
            conversation_id=conversation_id,
            message_text=user_message,
            customer_phone=customer_phone,
            sender_name=persona_name,
            customer_name=persona_name,
        )
        response = await self.capture_response(conversation_id=conversation_id, timeout=timeout)
        timestamp_received = response["timestamp_captured"]

        sent_dt = datetime.fromisoformat(timestamp_sent)
        received_dt = datetime.fromisoformat(timestamp_received)
        latency_ms = int((received_dt - sent_dt).total_seconds() * 1000)
        turn_number = self._turn_counters.get(conversation_id, 0) + 1
        self._turn_counters[conversation_id] = turn_number

        return {
            "turn_number": turn_number,
            "user_message": user_message,
            "agent_response": response.get("message", ""),
            "timestamp_sent": timestamp_sent,
            "timestamp_received": timestamp_received,
            "response_latency_ms": latency_ms,
            "raw_response": response["raw_payload"],
        }

    async def capture_final_state(self, conversation_id: str) -> dict[str, Any] | None:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        client = await self._get_binary_client()
        checkpointer = AsyncRedisSaver(redis_client=client)
        config = {"configurable": {"thread_id": conversation_id}}
        checkpoint = await checkpointer.aget(config)
        if checkpoint is None:
            return None

        if hasattr(checkpoint, "checkpoint"):
            checkpoint_data = checkpoint.checkpoint
        else:
            checkpoint_data = checkpoint

        channel_values = checkpoint_data.get("channel_values", {})
        return dict(channel_values) if isinstance(channel_values, dict) else {"raw": channel_values}

    async def close(self) -> None:
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(self.response_channel)
            await self._pubsub.close()
            self._pubsub = None
        if self._owns_binary_client and self.binary_redis is not None:
            await self.binary_redis.close()
            self.binary_redis = None

    async def _get_binary_client(self) -> redis.Redis:
        if self.binary_redis is None:
            settings = get_settings()
            self.binary_redis = redis.from_url(settings.REDIS_URL, decode_responses=False)
        return self.binary_redis
