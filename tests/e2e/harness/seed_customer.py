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
                sty_stmt = select(Stylist).where(func.lower(Stylist.name) == stylist_name.lower())
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


async def seed_future_appointment(
    *,
    phone: str,
    customer_name: str,
    hours_ahead: float,
    status: str = "confirmed",
    service_name: str | None = None,
    stylist_name: str | None = None,
) -> dict[str, Any]:
    """Seed a sandbox appointment placed at ``now(UTC) + hours_ahead``.

    Creates or reuses a Customer row for ``phone``, then inserts a future Appointment
    with ``reminder_sent_at = NULL``, ``confirmation_sent_at = NULL``, and
    ``gcal_sync_status = 'not_applicable'`` so the sandbox guard applies.

    When ``service_name`` / ``stylist_name`` are omitted, the first available
    Service / Stylist found in the DB are used.

    Args:
        phone: Customer phone in E.164 format.  MUST start with '+349'.
        customer_name: Full name split on first space into first/last name.
        hours_ahead: Offset in hours from now(UTC) for the appointment start.
            Use 24.0 to land in the reminder_24h window (23–25h),
            use 48.0 to land in the confirm_48h window (47–49h, PENDING only).
        status: AppointmentStatus name, e.g. 'confirmed' or 'pending'.
            confirm_48h handler only queries PENDING appointments.
        service_name: Case-insensitive service lookup (falls back to first row).
        stylist_name: Case-insensitive stylist lookup (falls back to first row).

    Returns:
        dict with keys:
            appointment_id (str): UUID of the inserted Appointment.
            customer_id (str): UUID of the upserted Customer.
            start_time (str): ISO-formatted start_time (UTC).

    Raises:
        ValueError: If phone does not start with '+349'.
        RuntimeError: If no Service or Stylist rows exist in the DB.
    """
    _assert_test_phone(phone)

    parts = customer_name.split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else None

    start_time = datetime.now(UTC) + timedelta(hours=hours_ahead)

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
            await session.flush()
            logger.info("seed_future_appointment: created Customer for %s", phone)
        else:
            logger.info("seed_future_appointment: found existing Customer for %s", phone)

        # --- Resolve Service ---
        if service_name:
            svc_stmt = select(Service).where(func.lower(Service.name) == service_name.lower())
        else:
            svc_stmt = select(Service).limit(1)
        svc_result = await session.execute(svc_stmt)
        service = svc_result.scalar_one_or_none()
        if service is None:
            raise RuntimeError(
                f"seed_future_appointment: no Service found "
                f"(service_name={service_name!r}) — seed the catalog first"
            )

        # --- Resolve Stylist ---
        if stylist_name:
            sty_stmt = select(Stylist).where(func.lower(Stylist.name) == stylist_name.lower())
        else:
            sty_stmt = select(Stylist).limit(1)
        sty_result = await session.execute(sty_stmt)
        stylist = sty_result.scalar_one_or_none()
        if stylist is None:
            raise RuntimeError(
                f"seed_future_appointment: no Stylist found "
                f"(stylist_name={stylist_name!r}) — seed stylists first"
            )

        appt = Appointment(
            id=uuid4(),
            customer_id=customer.id,
            stylist_id=stylist.id,
            service_ids=[service.id],
            start_time=start_time,
            duration_minutes=service.duration_minutes,
            status=AppointmentStatus[status.upper()],
            gcal_sync_status="not_applicable",
            first_name=customer.first_name,
            last_name=customer.last_name,
            # notification fields — explicitly NULL so handlers pick them up
            reminder_sent_at=None,
            confirmation_sent_at=None,
            reminder_failed=False,
            notification_failed=False,
        )
        session.add(appt)
        await session.flush()
        appointment_id = appt.id
        await session.commit()

    logger.info(
        "seed_future_appointment: inserted Appointment %s for %s (start_time=%s, status=%s)",
        appointment_id,
        phone,
        start_time.isoformat(),
        status,
    )
    return {
        "appointment_id": str(appointment_id),
        "customer_id": str(customer.id),
        "start_time": start_time.isoformat(),
    }
