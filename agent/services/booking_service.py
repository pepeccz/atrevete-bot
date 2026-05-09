"""
BookingService — atomic appointment creation.

Owns the full booking transaction:
  1. Fetch service duration (to compute end_time)
  2. Customer get-or-create (SELECT then INSERT+flush if new)
  3. Appointment INSERT + DB commit (source of truth)
  4. Fire-and-forget GCal push AFTER commit (non-blocking)

Session ownership: service opens and closes its own session.
Callers NEVER pass sessions in.

GCal failures: caught, logged, and ignored — DB is the source of truth.
Duplicate/exclusion violations: caught, returned as BookingResult(success=False, error_code="duplicate").

Design: SDD service-boundary-extraction PR#4, design D2/D4.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from agent.services.gcal_push_service import fire_and_forget_push_appointment
from database.connection import get_async_session
from database.models import Appointment, AppointmentStatus, Customer, Service, Stylist

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass (spec D2 interface)
# ---------------------------------------------------------------------------


@dataclass
class BookingResult:
    """Result of BookingService.create_appointment().

    success=True means the DB row was committed successfully.
    GCal push failures do NOT set success=False.

    service_names and stylist_display_name are populated after commit for
    use by the tool layer (calendar link generation). They may be empty
    strings if the post-commit fetches fail — this is non-critical.
    """

    success: bool
    appointment_id: UUID | None = None
    customer_id: UUID | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    error_message: str | None = None
    error_code: str | None = None  # "duplicate", "service_not_found", ...
    service_names: str = ""  # comma-joined service names for GCal link
    stylist_display_name: str = ""  # stylist display name for GCal link


# ---------------------------------------------------------------------------
# BookingService
# ---------------------------------------------------------------------------


class BookingService:
    """Service owning the full appointment creation transaction."""

    @staticmethod
    async def create_appointment(
        service_ids: list[UUID],
        stylist_id: UUID,
        start_at: datetime,
        customer_phone: str,
        first_name: str,
        last_name: str | None,
        notes: str | None = None,
    ) -> BookingResult:
        """Create an appointment atomically.

        Steps (all in one session):
          - Fetch service duration to compute end_time
          - Customer get-or-create by phone
          - Appointment INSERT + commit

        After commit:
          - Fire-and-forget GCal push (exceptions are caught, not re-raised)

        Returns BookingResult(success=True) on success.
        Returns BookingResult(success=False, error_code="duplicate") on
        IntegrityError (unique or exclusion constraint violation).
        Returns BookingResult(success=False, error_code="service_not_found")
        when the service IDs resolve to no duration rows.
        """
        # Ensure start_at is timezone-aware
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=UTC)

        appointment_id = uuid4()
        customer_id_out: UUID | None = None
        total_duration: int = 0
        end_time: datetime | None = None

        # --- Atomic DB transaction ---
        try:
            async with get_async_session() as session:
                # 1. Fetch service duration
                dur_result = await session.execute(
                    select(Service.duration_minutes).where(Service.id.in_(service_ids))
                )
                rows = dur_result.fetchall()
                if not rows:
                    return BookingResult(
                        success=False,
                        error_message="No se encontraron los servicios solicitados.",
                        error_code="service_not_found",
                    )
                total_duration = sum(row[0] for row in rows)
                end_time = start_at + timedelta(minutes=total_duration)

                # 2. Customer get-or-create
                cust_result = await session.execute(
                    select(Customer).where(Customer.phone == customer_phone)
                )
                customer = cust_result.scalar_one_or_none()
                if customer is None:
                    customer = Customer(
                        id=uuid4(),
                        phone=customer_phone,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    session.add(customer)
                    await session.flush()  # get the ID without committing
                customer_id_out = customer.id

                # 3. Insert appointment
                appointment = Appointment(
                    id=appointment_id,
                    customer_id=customer.id,
                    stylist_id=stylist_id,
                    service_ids=service_ids,
                    start_time=start_at,
                    duration_minutes=total_duration,
                    status=AppointmentStatus.PENDING,
                    first_name=first_name,
                    last_name=last_name,
                    notes=notes,
                )
                session.add(appointment)
                await session.commit()

        except IntegrityError as exc:
            logger.error("BookingService: IntegrityError creating appointment: %s", exc)
            error_msg = str(exc).lower()
            if "duplicate" in error_msg or "unique" in error_msg or "exclusion" in error_msg:
                return BookingResult(
                    success=False,
                    error_message="El horario solicitado ya está ocupado.",
                    error_code="duplicate",
                )
            return BookingResult(
                success=False,
                error_message=f"Error de integridad al crear la cita: {exc}",
                error_code="duplicate",
            )
        except Exception as exc:
            logger.error("BookingService: unexpected error creating appointment: %s", exc, exc_info=True)
            return BookingResult(
                success=False,
                error_message=f"La cita no pudo registrarse: {exc}",
                error_code="error",
            )

        # --- GCal push (fire-and-forget, AFTER commit, non-blocking) ---
        # Fetch service names + stylist display name for GCal push / calendar link
        # These are non-critical: failures do not affect the booking result.
        service_names = ""
        stylist_display_name = str(stylist_id)  # fallback to UUID string
        try:
            async with get_async_session() as session:
                svc_result = await session.execute(
                    select(Service.name).where(Service.id.in_(service_ids))
                )
                service_names = ", ".join(row[0] for row in svc_result.fetchall())

                sty_result = await session.execute(
                    select(Stylist.name).where(Stylist.id == stylist_id)
                )
                sty_name = sty_result.scalar_one_or_none()
                if sty_name:
                    stylist_display_name = sty_name

            await fire_and_forget_push_appointment(
                appointment_id=appointment_id,
                stylist_id=stylist_id,
                customer_name=f"{first_name} {last_name or ''}".strip(),
                service_names=service_names,
                start_time=start_at,
                duration_minutes=total_duration,
                status="pending",
                notes=notes,
            )
        except Exception as exc:
            # GCal push failure does NOT undo the DB commit — fire-and-forget
            logger.error("BookingService: GCal push failed (appointment saved): %s", exc, exc_info=True)

        return BookingResult(
            success=True,
            appointment_id=appointment_id,
            customer_id=customer_id_out,
            start_time=start_at,
            end_time=end_time,
            service_names=service_names,
            stylist_display_name=stylist_display_name,
        )
