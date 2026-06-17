"""
Seed helpers for returning-customer QA scenarios.

Writes a Customer row, an optional past Appointment row, and agent memories
into the test store so the bot starts a conversation with full returning-customer
context already loaded.

Phone numbers MUST start with the +349 test prefix (enforced via guard).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

# Module-level imports for patchability in tests.
# Wrapped in try/except so the module can be imported even when the full
# service stack is not installed (e.g. lightweight test environments).
try:
    from database.connection import AsyncSessionLocal
    from database.models import Appointment, AppointmentStatus, Customer, Service, Stylist
except ImportError:  # pragma: no cover
    AsyncSessionLocal = None  # type: ignore[assignment,misc]
    Appointment = None  # type: ignore[assignment,misc]
    AppointmentStatus = None  # type: ignore[assignment,misc]
    Customer = None  # type: ignore[assignment,misc]
    Service = None  # type: ignore[assignment,misc]
    Stylist = None  # type: ignore[assignment,misc]

try:
    from agent.services.customer_memory_service import (
        NAMESPACE_PREFIX,
        PREFERENCES_KEY,
        _get_store_safe,
    )
except ImportError:  # pragma: no cover
    NAMESPACE_PREFIX = "customer_memories"  # type: ignore[assignment]
    PREFERENCES_KEY = "preferences"  # type: ignore[assignment]
    _get_store_safe = None  # type: ignore[assignment]

_TEST_PHONE_PREFIX = "+349"


def _assert_test_phone(phone: str) -> None:
    """Raise ValueError if phone does not start with the test prefix."""
    if not phone.startswith(_TEST_PHONE_PREFIX):
        raise ValueError(
            f"seed_returning_customer: phone {phone!r} does not start with "
            f"{_TEST_PHONE_PREFIX!r} — refusing to seed non-test data"
        )


async def seed_returning_customer(
    *,
    phone: str,
    customer_name: str,
    memories: dict[str, Any],
    past_appointment: dict | None = None,
) -> dict[str, Any]:
    """Seed a returning customer with memories and an optional past appointment.

    Creates or updates a Customer row, optionally inserts a past Appointment row,
    and writes agent memories both to the Redis Store and to the Customer.metadata_
    fallback path.

    Args:
        phone: Customer phone in E.164 format. MUST start with '+349'.
        customer_name: Full name (e.g. "Ana Torres"). Split on first space into
            first_name / last_name; if no space, first_name = customer_name.
        memories: Dict to write directly to the memory store (no merge logic applied).
            Common keys: visit_count, preferred_stylist_name, typical_services,
            agent_notes, last_visit_date, etc.
        past_appointment: Optional dict with keys:
            - days_ago (int): How many days in the past the appointment was.
            - service_name (str): Service name (case-insensitive lookup).
            - stylist_name (str): Stylist name (case-insensitive lookup).
            - status (str, default "completed"): AppointmentStatus name.

    Returns:
        dict with keys:
            - customer_id (str): UUID of the upserted Customer.
            - past_appointment_id (str | None): UUID of the inserted Appointment, or None.
            - memories_written_keys (list[str]): Keys from the memories dict that were saved.

    Raises:
        ValueError: If phone does not start with '+349'.
    """
    _assert_test_phone(phone)

    # Split customer name into first / last
    parts = customer_name.split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else None

    customer_id: Any = None
    appointment_id: Any = None

    async with AsyncSessionLocal() as session:
        # --- Upsert Customer ---
        stmt = select(Customer).where(Customer.phone == phone)
        result = await session.execute(stmt)
        customer = result.scalar_one_or_none()

        if customer is None:
            customer = Customer(
                id=uuid4(),
                phone=phone,
                first_name=first_name,
                last_name=last_name,
                metadata_={},
            )
            session.add(customer)
            await session.flush()  # get the id without committing
            logger.info("seed_returning_customer: created Customer for %s", phone)
        else:
            logger.info("seed_returning_customer: found existing Customer for %s", phone)

        customer_id = customer.id

        # --- Optional past Appointment ---
        appt_status = "completed"
        if past_appointment is not None:
            days_ago = int(past_appointment["days_ago"])
            service_name = past_appointment["service_name"]
            stylist_name = past_appointment["stylist_name"]
            appt_status = past_appointment.get("status", "completed")

            # Look up Service (case-insensitive)
            svc_stmt = select(Service).where(func.lower(Service.name) == service_name.lower())
            svc_result = await session.execute(svc_stmt)
            service = svc_result.scalar_one_or_none()

            if service is None:
                logger.warning(
                    "seed_returning_customer: Service %r not found — skipping appointment",
                    service_name,
                )
            else:
                # Look up Stylist (case-insensitive)
                sty_stmt = select(Stylist).where(
                    func.lower(Stylist.name) == stylist_name.lower()
                )
                sty_result = await session.execute(sty_stmt)
                stylist = sty_result.scalar_one_or_none()

                if stylist is None:
                    logger.warning(
                        "seed_returning_customer: Stylist %r not found — skipping appointment",
                        stylist_name,
                    )
                else:
                    start_time = datetime.now(UTC) - timedelta(days=days_ago)
                    appt = Appointment(
                        id=uuid4(),
                        customer_id=customer.id,
                        stylist_id=stylist.id,
                        service_ids=[service.id],
                        start_time=start_time,
                        duration_minutes=service.duration_minutes,
                        status=AppointmentStatus[appt_status.upper()],
                        gcal_sync_status="not_applicable",
                        first_name=customer.first_name,
                        last_name=customer.last_name,
                    )
                    session.add(appt)
                    await session.flush()
                    appointment_id = appt.id
                    logger.info(
                        "seed_returning_customer: inserted past Appointment %s for %s",
                        appointment_id,
                        phone,
                    )

        # --- Write memories to Customer.metadata_ (DB fallback path) ---
        existing_meta = customer.metadata_ or {}
        customer.metadata_ = {**existing_meta, "memories": memories}

        await session.commit()
        logger.info(
            "seed_returning_customer: committed DB writes for %s (customer_id=%s)",
            phone,
            customer_id,
        )

    # --- Write memories to Redis Store (primary path) ---
    try:
        store = _get_store_safe() if _get_store_safe is not None else None
        if store is not None:
            await store.aput(
                namespace=(NAMESPACE_PREFIX, phone),
                key=PREFERENCES_KEY,
                value=memories,
            )
            logger.info("seed_returning_customer: Store write OK for %s", phone)
        else:
            logger.warning(
                "seed_returning_customer: Store unavailable — memories written to DB only for %s",
                phone,
            )
    except Exception as exc:
        logger.warning(
            "seed_returning_customer: Store write failed for %s: %s — memories in DB only",
            phone,
            exc,
        )

    return {
        "customer_id": str(customer_id),
        "past_appointment_id": str(appointment_id) if appointment_id is not None else None,
        "memories_written_keys": list(memories.keys()),
    }
