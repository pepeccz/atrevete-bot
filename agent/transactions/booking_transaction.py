"""
Atomic Booking Transaction Handler.

This module implements the core booking logic as a single atomic transaction that:
1. Validates all preconditions
2. Creates provisional appointment in PostgreSQL
3. Creates Google Calendar event (yellow = provisional)
4. Generates Stripe payment link (if required)
5. Auto-confirms if free (no payment required)
6. Rolls back completely on any failure

This replaces 5 nodes from v2 architecture:
- booking_handler
- validate_booking_request
- create_provisional_booking
- generate_payment_link
- Auto-confirmation logic

The handler ensures ACID properties using:
- SERIALIZABLE isolation level
- SELECT FOR UPDATE row locks
- Comprehensive rollback on errors
- Idempotency (safe to retry)
"""

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import Appointment, Customer, Service, Stylist

logger = logging.getLogger(__name__)


class BookingTransaction:
    """
    Atomic transaction handler for creating bookings.

    This class encapsulates all the logic for creating a provisional or confirmed
    booking, coordinating between:
    - PostgreSQL (appointment data)
    - Google Calendar (event creation with color coding)
    - Stripe (payment link generation)

    Usage:
        transaction = BookingTransaction()
        result = await transaction.execute(
            services=["Corte de Caballero"],
            slot={"time": "10:00", "date": "2025-11-08", "stylist_id": "uuid", ...},
            customer_phone="+34612345678",
            customer_name="Pedro Gómez",
            customer_notes=None
        )

        if result["success"]:
            appointment_id = result["appointment_id"]
            payment_link = result.get("payment_link")
            # ... send payment link to customer
        else:
            error_code = result["error_code"]
            # ... handle error conversationally

    Error Codes:
        - SERVICE_NOT_FOUND: Service name not in database
        - SERVICE_AMBIGUOUS: Multiple services match name
        - CATEGORY_MISMATCH: Mix of Peluquería + Estética services
        - DATE_TOO_SOON: Booking < 3 days from now
        - SLOT_TAKEN: Slot occupied by concurrent booking
        - BUFFER_CONFLICT: <10 min buffer with existing appointment
        - CALENDAR_ERROR: Google Calendar API failure
        - STRIPE_ERROR: Stripe API failure
        - TRANSACTION_FAILED: General error

    Transaction Steps:
        1. Validate preconditions (services exist, category consistent, 3-day rule)
        2. BEGIN TRANSACTION (SERIALIZABLE)
        3. Check slot availability with row lock
        4. INSERT Appointment (status=provisional)
        5. Create Google Calendar event (yellow color)
        6. Generate Stripe payment link (if price > 0)
        7. Auto-confirm if price = 0
        8. COMMIT
        9. If any step fails → ROLLBACK + cleanup external APIs
    """

    def __init__(self):
        """Initialize transaction handler."""
        self.session: AsyncSession | None = None
        self.appointment_id: UUID | None = None
        self.calendar_event_id: str | None = None
        self.stripe_payment_link_id: str | None = None
        self.trace_id: str = str(uuid4())

    async def execute(
        self,
        services: list[str],
        slot: dict,
        customer_phone: str,
        customer_name: str | None = None,
        customer_notes: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute atomic booking transaction.

        Args:
            services: List of service names (e.g., ["Corte de Caballero", "Barba"])
            slot: Selected slot from check_availability() result:
                {
                    "time": "10:00",
                    "end_time": "11:30",
                    "date": "2025-11-08",
                    "stylist_id": "uuid-stylist",
                    "stylist_name": "María",
                    "duration_minutes": 90,
                    "total_price": 50.0
                }
            customer_phone: Phone in E.164 format (e.g., +34612345678)
            customer_name: Full name if customer doesn't exist (optional)
            customer_notes: Additional notes (allergies, preferences, etc.)

        Returns:
            Success case:
                {
                    "success": True,
                    "appointment_id": "uuid",
                    "payment_required": True,
                    "payment_link": "https://checkout.stripe.com/...",
                    "payment_timeout_minutes": 10,
                    "summary": {
                        "date": "viernes 8 de noviembre",
                        "time": "10:00",
                        "end_time": "11:30",
                        "stylist": "María",
                        "services": ["Corte de Caballero"],
                        "duration_minutes": 90,
                        "total_price_euros": 50.0,
                        "advance_payment_euros": 10.0
                    }
                }

            Error case:
                {
                    "success": False,
                    "error_code": "SLOT_TAKEN",
                    "error_message": "El horario se ocupó hace un momento.",
                    "retry_possible": True,
                    "suggested_action": "Llama check_availability de nuevo"
                }
        """
        logger.info(
            "BookingTransaction started",
            extra={
                "trace_id": self.trace_id,
                "services": services,
                "slot": slot,
                "customer_phone": customer_phone,
            },
        )

        try:
            # Step 1: Validate preconditions (before starting DB transaction)
            logger.info(f"Step 1: Validating preconditions", extra={"trace_id": self.trace_id})

            # Implementation to be completed in Phase 3 (Day 4)
            raise NotImplementedError(
                "BookingTransaction.execute() will be implemented in Phase 3, Day 4"
            )

        except Exception as e:
            # Step 9: Rollback + cleanup
            logger.error(
                "BookingTransaction failed",
                extra={
                    "trace_id": self.trace_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            # Cleanup external APIs if needed
            await self._rollback_calendar_event()

            return {
                "success": False,
                "error_code": "TRANSACTION_FAILED",
                "error_message": str(e),
                "retry_possible": False,
            }

    async def _resolve_services(self, service_names: list[str]) -> list[UUID]:
        """
        Resolve service names to UUIDs using fuzzy matching.

        Args:
            service_names: List of service names

        Returns:
            List of resolved Service UUIDs

        Raises:
            ValueError: If any service not found or ambiguous
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _validate_category_consistency(self, service_ids: list[UUID]) -> None:
        """
        Validate all services belong to same category.

        Args:
            service_ids: List of Service UUIDs

        Raises:
            ValueError: If services mix Peluquería + Estética categories
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _validate_3_day_rule(self, date_str: str) -> None:
        """
        Validate booking date meets 3-day minimum notice requirement.

        Args:
            date_str: Date in ISO format (e.g., "2025-11-08")

        Raises:
            ValueError: If date < 3 days from now
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _get_or_create_customer(
        self, phone: str, name: str | None
    ) -> Customer:
        """
        Get existing customer or create new one.

        Args:
            phone: Phone in E.164 format
            name: Full name (required if customer doesn't exist)

        Returns:
            Customer object

        Raises:
            ValueError: If customer doesn't exist and name not provided
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _check_slot_with_lock(
        self, stylist_id: UUID, start_time: str, duration_minutes: int
    ) -> bool:
        """
        Check slot availability with database row lock.

        Uses SELECT FOR UPDATE to prevent race conditions.

        Args:
            stylist_id: Stylist UUID
            start_time: Start time in ISO format
            duration_minutes: Duration including 10-min buffer

        Returns:
            True if slot available, False otherwise
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _create_provisional_appointment(
        self,
        customer_id: UUID,
        stylist_id: UUID,
        service_ids: list[UUID],
        start_time: str,
        duration_minutes: int,
        total_price: Decimal,
    ) -> Appointment:
        """
        Create provisional appointment in database.

        Args:
            customer_id: Customer UUID
            stylist_id: Stylist UUID
            service_ids: List of Service UUIDs
            start_time: Start time in ISO format
            duration_minutes: Total duration
            total_price: Total price in euros

        Returns:
            Created Appointment object
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _create_calendar_event(self, appointment: Appointment) -> dict:
        """
        Create Google Calendar event for provisional booking.

        Event properties:
        - Title: "[PROVISIONAL] {customer_name} - {services}"
        - Color: Yellow (#FFFF00)
        - Duration: duration_minutes + 10 min buffer
        - Calendar: stylist's google_calendar_id

        Args:
            appointment: Appointment object

        Returns:
            dict with event details including "id"
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _generate_payment_link(self, appointment: Appointment) -> dict:
        """
        Generate Stripe payment link for advance payment (20% of total).

        Args:
            appointment: Appointment object

        Returns:
            dict with payment link details including "url"
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _auto_confirm_free_appointment(self, appointment: Appointment) -> None:
        """
        Auto-confirm appointment if price = 0 (no payment required).

        Updates:
        - Appointment status: provisional → confirmed
        - Calendar event color: yellow → green

        Args:
            appointment: Appointment object
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()

    async def _rollback_calendar_event(self) -> None:
        """
        Delete Google Calendar event if it was created.

        Called during rollback if transaction fails after calendar event creation.
        """
        if self.calendar_event_id:
            try:
                logger.warning(
                    "Rolling back calendar event",
                    extra={
                        "trace_id": self.trace_id,
                        "calendar_event_id": self.calendar_event_id,
                    },
                )
                # Delete calendar event
                # Implementation to be completed in Phase 3, Day 4
            except Exception as e:
                logger.error(
                    "Failed to rollback calendar event",
                    extra={
                        "trace_id": self.trace_id,
                        "error": str(e),
                    },
                )

    def _build_summary(self, appointment: Appointment) -> dict:
        """
        Build summary dictionary for successful booking response.

        Args:
            appointment: Appointment object

        Returns:
            dict with human-readable appointment summary
        """
        # Implementation to be completed in Phase 3, Day 4
        raise NotImplementedError()
