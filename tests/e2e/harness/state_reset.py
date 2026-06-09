"""State reset helpers for conversational QA tests."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.config import get_settings

if TYPE_CHECKING:
    from tests.e2e.harness.run_models import QARunIdentity


def _get_qa_phone_prefix() -> str:
    """Return the QA phone prefix from Settings.

    Raises RuntimeError if the prefix is empty or does not start with '+349'
    (guard against misconfiguration that could point at real Spanish mobile numbers).
    """
    prefix = get_settings().TEST_PHONE_PREFIX.strip()
    if not prefix:
        raise RuntimeError("TEST_PHONE_PREFIX is empty — refusing QA cleanup")
    if not prefix.startswith("+349"):
        raise RuntimeError(
            f"TEST_PHONE_PREFIX must start with +349 (got: {prefix!r}) — refusing QA cleanup"
        )
    return prefix


class ProtectedDataError(RuntimeError):
    """Raised when a cleanup operation would touch non-test data."""


def is_test_phone(phone: str) -> bool:
    """Return True only if phone starts with the QA test prefix."""
    return phone.startswith(_get_qa_phone_prefix())


def is_test_conversation(conversation_id: str, run_identity: QARunIdentity) -> bool:
    """Return True only if conversation_id matches the run identity."""
    return conversation_id == run_identity.conversation_id


async def safe_delete_customer(session: AsyncSession, phone: str) -> int:
    """Delete a test customer by phone. Raises ProtectedDataError for non-test phones."""
    if not is_test_phone(phone):
        raise ProtectedDataError(
            f"Refusing to delete non-test data: phone={phone!r} "
            f"(must start with {_get_qa_phone_prefix()!r})"
        )
    result = await session.execute(
        text("DELETE FROM customers WHERE phone = :phone"),
        {"phone": phone},
    )
    return result.rowcount


async def safe_delete_appointments(session: AsyncSession, phone: str) -> int:
    """Delete all appointments for a test customer by phone.

    Raises ProtectedDataError for non-test phones.
    """
    if not is_test_phone(phone):
        raise ProtectedDataError(
            f"Refusing to delete non-test data: phone={phone!r} "
            f"(must start with {_get_qa_phone_prefix()!r})"
        )
    result = await session.execute(
        text(
            "DELETE FROM appointments WHERE customer_id = "
            "(SELECT id FROM customers WHERE phone = :phone LIMIT 1)"
        ),
        {"phone": phone},
    )
    return result.rowcount


async def safe_delete_conversation(
    session: AsyncSession, conversation_id: str, run_identity: QARunIdentity
) -> int:
    """Delete conversation history for a test conversation.

    Raises ProtectedDataError if conversation_id doesn't match the run identity.
    """
    if not is_test_conversation(conversation_id, run_identity):
        raise ProtectedDataError(
            f"Refusing to delete non-test data: conversation_id={conversation_id!r} "
            f"does not match run identity {run_identity.conversation_id!r}"
        )
    result = await session.execute(
        text("DELETE FROM conversation_history WHERE conversation_id = :cid"),
        {"cid": conversation_id},
    )
    return result.rowcount


class AsyncDatabaseCleaner:
    """Async database cleaner for QA test cleanup and verification."""

    def __init__(self, db_url: str, run_identity: QARunIdentity):
        self._db_url = db_url
        self._run_identity = run_identity
        self._engine: Any = None

    @asynccontextmanager
    async def _session_context(self):
        """Context manager that yields a database session."""
        if self._engine is None:
            self._engine = create_async_engine(self._db_url, echo=False)
        async with AsyncSession(self._engine) as session:
            yield session

    async def verify_appointment(
        self,
        phone: str,
        service_name: str,
        stylist_name: str,
        start_datetime: datetime,
    ) -> dict[str, Any] | None:
        """Verify an appointment exists and return normalized row or None."""
        from database.models import Appointment, Customer, Service, Stylist

        stmt = (
            select(Appointment, Customer, Service, Stylist)
            .join(Customer, Appointment.customer_id == Customer.id)
            .join(Stylist, Appointment.stylist_id == Stylist.id)
            .join(Service, Service.id.in_(Appointment.service_ids))
            .where(Customer.phone == phone)
            .where(Service.name == service_name)
            .where(Stylist.name == stylist_name)
            .limit(1)
        )

        async with self._session_context() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        if row is None:
            return None

        appointment, customer, service, stylist = row
        return {
            "appointment_id": appointment.id,
            "customer_id": appointment.customer_id,
            "customer_phone": customer.phone,
            "service_name": service.name,
            "stylist_name": stylist.name,
            "start_datetime": appointment.start_time,
            "created_at": appointment.created_at,
            "status": appointment.status.value
            if hasattr(appointment.status, "value")
            else str(appointment.status),
        }

    async def close(self) -> None:
        """Close the database engine."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


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

        Safety: only processes phone numbers starting with the configured
        TEST_PHONE_PREFIX (+34999 by default) to prevent accidental deletion
        of real customer data.

        Returns a dict with:
            appointments_deleted (int): number of appointments removed.
            customer_deleted (bool): True if the customer row was removed.
        """
        if not phone or not phone.startswith(_get_qa_phone_prefix()):
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
