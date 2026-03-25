"""State reset helpers for conversational QA tests."""

from __future__ import annotations

from typing import Iterable

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Safety guard: only allow DB cleanup for QA test phone numbers.
# This prevents accidental deletion of real customer data.
_QA_PHONE_PREFIX = "+34999"


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

    async def cleanup_db(self, phone: str) -> dict[str, int | bool]:
        """Delete all PostgreSQL data for a QA test phone number.

        Creates its own DB session — no injection needed.

        Safety: only processes phone numbers starting with ``_QA_PHONE_PREFIX``
        (+34999) to prevent accidental deletion of real customer data.

        Returns a dict with:
            appointments_deleted (int): number of appointments removed.
            customer_deleted (bool): True if the customer row was removed.
        """
        if not phone or not phone.startswith(_QA_PHONE_PREFIX):
            # Not a QA number — refuse to touch the DB.
            return {"appointments_deleted": 0, "customer_deleted": False}

        from database.connection import get_async_session

        appointments_deleted = 0
        customer_deleted = False

        async with get_async_session() as session:
            # Delete appointments first (FK constraint: appointments.customer_id
            # references customers.id with ondelete="CASCADE", but we delete
            # explicitly so we can report the count).
            appt_result = await session.execute(
                text(
                    "DELETE FROM appointments "
                    "WHERE customer_id = ("
                    "  SELECT id FROM customers WHERE phone = :phone LIMIT 1"
                    ")"
                ),
                {"phone": phone},
            )
            appointments_deleted = appt_result.rowcount

            # Delete conversation history rows linked to this customer
            # (CASCADE will remove messages automatically).
            await session.execute(
                text(
                    "DELETE FROM conversation_history "
                    "WHERE customer_id = ("
                    "  SELECT id FROM customers WHERE phone = :phone LIMIT 1"
                    ")"
                ),
                {"phone": phone},
            )

            # Delete the customer row itself.
            cust_result = await session.execute(
                text("DELETE FROM customers WHERE phone = :phone"),
                {"phone": phone},
            )
            customer_deleted = cust_result.rowcount > 0

            await session.commit()

        return {
            "appointments_deleted": appointments_deleted,
            "customer_deleted": customer_deleted,
        }

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
        customer_redis_deleted = await self.reset_customer_data(customer_phone)
        artifacts_deleted = await self.reset_test_artifacts(conversation_id)

        # DB cleanup — creates its own session, safe for QA phone numbers only.
        db_result = await self.cleanup_db(customer_phone or "")

        # Re-seed stylists after cleanup so they are always present for the next test.
        # seed_stylists() is idempotent (check-before-insert by slug) so this is safe.
        from database.seeds.stylists import seed_stylists

        await seed_stylists()

        clean = await self.verify_clean(conversation_id)
        return {
            "checkpoints_deleted": checkpoints_deleted,
            "customer_redis_deleted": customer_redis_deleted,
            "artifacts_deleted": artifacts_deleted,
            "appointments_deleted": db_result["appointments_deleted"],
            "customer_deleted": db_result["customer_deleted"],
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
