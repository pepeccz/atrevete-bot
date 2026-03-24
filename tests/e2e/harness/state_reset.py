"""State reset helpers for conversational QA tests."""

from __future__ import annotations

from typing import Iterable

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class StateResetHarness:
    """Reset Redis + PostgreSQL artifacts created during QA conversations."""

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession | None = None,
    ):
        self.redis = redis_client
        self.db_session = db_session

    async def reset_conversation_checkpoints(self, conversation_id: str) -> int:
        """Reset all LangGraph checkpoint key families for a conversation.
        
        Matches production patterns from conversation_delete_service.py:
        - checkpoint:{thread_id}:*
        - checkpoint_write:{thread_id}:*
        - write_keys_zset:{thread_id}:*
        """
        return await self._delete_matching_patterns(
            [
                f"checkpoint:{conversation_id}:*",
                f"checkpoint_write:{conversation_id}:*",
                f"write_keys_zset:{conversation_id}:*",
                # Legacy patterns for backwards compatibility
                f"langgraph:checkpoint:*{conversation_id}*",
            ]
        )

    async def reset_customer_data(self, customer_phone: str | None = None) -> int:
        if not customer_phone:
            return 0
        return await self._delete_matching_patterns(
            [
                f"customer:*{customer_phone}*",
                f"conversation:*{customer_phone}*",
            ]
        )

    async def reset_db_customer(self, phone: str) -> bool:
        """Delete a customer from PostgreSQL by exact phone match.

        Returns True if a row was deleted, False otherwise.
        """
        if not self.db_session or not phone:
            return False
        result = await self.db_session.execute(
            text("DELETE FROM customers WHERE phone = :phone"),
            {"phone": phone},
        )
        await self.db_session.commit()
        return result.rowcount > 0

    async def reset_test_artifacts(self, conversation_id: str) -> int:
        return await self._delete_matching_patterns(
            [
                f"batcher:pending:{conversation_id}",
                f"conversation:{conversation_id}:*",
            ]
        )

    async def reset_conversation_state(
        self,
        conversation_id: str,
        customer_phone: str | None = "+34600000000",
    ) -> dict[str, int | bool]:
        checkpoints_deleted = await self.reset_conversation_checkpoints(conversation_id)
        customer_deleted = await self.reset_customer_data(customer_phone)
        artifacts_deleted = await self.reset_test_artifacts(conversation_id)
        db_customer_deleted = await self.reset_db_customer(customer_phone or "")
        clean = await self.verify_clean(conversation_id)
        return {
            "checkpoints_deleted": checkpoints_deleted,
            "customer_deleted": customer_deleted,
            "artifacts_deleted": artifacts_deleted,
            "db_customer_deleted": db_customer_deleted,
            "clean": clean,
        }

    async def verify_clean(self, conversation_id: str) -> bool:
        async for _ in self.redis.scan_iter(match=f"*{conversation_id}*"):
            return False
        return True

    async def _delete_matching_patterns(self, patterns: Iterable[str]) -> int:
        deleted = 0
        seen: set[str] = set()
        for pattern in patterns:
            async for key in self.redis.scan_iter(match=pattern):
                key_name = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                if key_name in seen:
                    continue
                seen.add(key_name)
                deleted += await self.redis.delete(key)
        return deleted
