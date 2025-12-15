"""
BookingFSM - Finite State Machine controller for booking flow.

This module implements the core FSM that controls the booking conversation flow.
The FSM validates state transitions and accumulates data as the user progresses
through the booking process.

Key responsibilities:
- Validate state transitions based on current state and intent
- Accumulate booking data (services, stylist, slot, customer info)
- Serialize state for checkpoint persistence (ADR-011: single source of truth)
- Log all transitions for debugging and monitoring
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from agent.utils.date_parser import format_date_spanish
from agent.fsm.models import (
    ActionType,
    BookingState,
    FSMAction,
    FSMResult,
    Intent,
    IntentType,
    ResponseGuidance,
    ServiceDetail,
    ToolCall,
)

logger = logging.getLogger(__name__)


class BookingFSM:
    """
    Finite State Machine controller for booking flow.

    Controls the booking conversation flow by validating transitions,
    accumulating data, and persisting state to Redis.

    Attributes:
        conversation_id: Unique identifier for the conversation
        state: Current FSM state
        collected_data: Accumulated booking data

    Example:
        >>> fsm = BookingFSM("conv-123")
        >>> intent = Intent(type=IntentType.START_BOOKING)
        >>> result = fsm.transition(intent)
        >>> result.success
        True
        >>> fsm.state
        BookingState.SERVICE_SELECTION
    """

    # Valid state transitions: from_state -> {intent_type: to_state}
    # Note: Some intents stay in same state (self-loop) to accumulate data
    TRANSITIONS: ClassVar[dict[BookingState, dict[IntentType, BookingState]]] = {
        BookingState.IDLE: {
            IntentType.START_BOOKING: BookingState.SERVICE_SELECTION,
        },
        BookingState.SERVICE_SELECTION: {
            # SELECT_SERVICE stays in same state but accumulates services
            IntentType.SELECT_SERVICE: BookingState.SERVICE_SELECTION,
            IntentType.CONFIRM_SERVICES: BookingState.STYLIST_SELECTION,
            # SELECT_STYLIST allows skipping explicit confirmation when LLM shows stylists
            # Requires at least 1 service in collected_data (validated in TRANSITION_REQUIREMENTS)
            IntentType.SELECT_STYLIST: BookingState.STYLIST_SELECTION,
        },
        BookingState.STYLIST_SELECTION: {
            IntentType.SELECT_STYLIST: BookingState.SLOT_SELECTION,
        },
        BookingState.SLOT_SELECTION: {
            IntentType.SELECT_SLOT: BookingState.CUSTOMER_DATA,
            # Allow re-checking availability with different dates while in slot selection
            IntentType.CHECK_AVAILABILITY: BookingState.SLOT_SELECTION,
            # v4.2: Confirm stylist change when selecting soonest_any with different stylist
            IntentType.CONFIRM_STYLIST_CHANGE: BookingState.CUSTOMER_DATA,
        },
        BookingState.CUSTOMER_DATA: {
            # Self-loop to accumulate data in enhanced 3-phase flow (v6.0):
            # Phase 1a: Ask who the appointment is for
            # Phase 1b: Confirm customer name (if use_customer_name=True)
            # Phase 1c: Request third-party name (if needed)
            # Phase 2: Ask for notes (notes_asked=True)
            # After phase 2 completes, transition() advances to CONFIRMATION
            IntentType.PROVIDE_CUSTOMER_DATA: BookingState.CUSTOMER_DATA,
            IntentType.USE_CUSTOMER_NAME: BookingState.CUSTOMER_DATA,  # v6.0
            IntentType.PROVIDE_THIRD_PARTY_BOOKING: BookingState.CUSTOMER_DATA,  # v6.0
            IntentType.CONFIRM_NAME: BookingState.CUSTOMER_DATA,  # v6.0
            IntentType.CORRECT_NAME: BookingState.CUSTOMER_DATA,  # v6.0
        },
        BookingState.CONFIRMATION: {
            IntentType.CONFIRM_BOOKING: BookingState.BOOKED,
        },
        BookingState.BOOKED: {
            IntentType.START_BOOKING: BookingState.SERVICE_SELECTION,
        },  # Allows starting new booking from booked state
    }

    # Intents that accumulate data without requiring validation
    # These are "stay-in-state" intents that just add data
    DATA_ACCUMULATION_INTENTS: ClassVar[set[IntentType]] = {
        IntentType.SELECT_SERVICE,  # Adds to services[] list
    }

    # Data validation requirements for each transition
    # NOTE: notes_asked is a boolean flag indicating that the user was asked for notes
    # It doesn't require actual notes content, just that the question was asked
    TRANSITION_REQUIREMENTS: ClassVar[dict[tuple[BookingState, IntentType], list[str]]] = {
        (BookingState.SERVICE_SELECTION, IntentType.CONFIRM_SERVICES): ["services"],
        # SELECT_STYLIST from SERVICE_SELECTION requires at least 1 service selected
        (BookingState.SERVICE_SELECTION, IntentType.SELECT_STYLIST): ["services", "stylist_id"],
        (BookingState.STYLIST_SELECTION, IntentType.SELECT_STYLIST): ["stylist_id"],
        (BookingState.SLOT_SELECTION, IntentType.SELECT_SLOT): ["slot"],
        # CUSTOMER_DATA: No requirements for self-loop - data accumulated in phases
        # Phase progression (first_name → notes_asked) handled in transition()
        (BookingState.CUSTOMER_DATA, IntentType.PROVIDE_CUSTOMER_DATA): [],
        (BookingState.CONFIRMATION, IntentType.CONFIRM_BOOKING): [
            "services",
            "stylist_id",
            "slot",
            "first_name",
        ],
    }

    def __init__(self, conversation_id: str) -> None:
        """
        Initialize BookingFSM for a conversation.

        Args:
            conversation_id: Unique identifier for the conversation
        """
        self._conversation_id = conversation_id
        self._state = BookingState.IDLE
        self._collected_data: dict[str, Any] = {}
        self._last_updated = datetime.now(UTC)

    @property
    def conversation_id(self) -> str:
        """Get the conversation ID."""
        return self._conversation_id

    @property
    def state(self) -> BookingState:
        """Get current FSM state."""
        return self._state

    @property
    def collected_data(self) -> dict[str, Any]:
        """Get accumulated booking data."""
        return self._collected_data.copy()

    def can_transition(self, intent: Intent) -> bool:
        """
        Check if a transition is valid for the given intent.

        Args:
            intent: The intent to check

        Returns:
            True if the transition is valid, False otherwise
        """
        # Cancel is always allowed from any state
        if intent.type == IntentType.CANCEL_BOOKING:
            return True

        # Check if transition exists for current state and intent
        valid_transitions = self.TRANSITIONS.get(self._state, {})
        if intent.type not in valid_transitions:
            return False

        # Check data requirements
        requirements = self.TRANSITION_REQUIREMENTS.get((self._state, intent.type), [])
        merged_data = {**self._collected_data, **intent.entities}

        for required_field in requirements:
            value = merged_data.get(required_field)
            if value is None:
                return False
            # Check for empty lists/strings
            if isinstance(value, (list, str)) and len(value) == 0:
                return False

        return True

    def _validate_slot_structure(self, slot: dict) -> tuple[bool, list[str]]:
        """
        Validate slot has required fields and correct format.

        This is a structural validation that checks:
        - Slot has start_time field
        - start_time is valid ISO 8601 format
        - start_time has specific time (not just date with 00:00:00)
        - duration_minutes is positive integer

        Args:
            slot: Slot dictionary to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
            - (True, []) if slot is structurally valid
            - (False, ["error1", "error2"]) if slot has structural issues

        Example:
            >>> slot = {"start_time": "2025-12-09T10:00:00+01:00", "duration_minutes": 60}
            >>> is_valid, errors = self._validate_slot_structure(slot)
            >>> # Returns: (True, [])

            >>> bad_slot = {"start_time": "2025-12-09T00:00:00+01:00", "duration_minutes": 0}
            >>> is_valid, errors = self._validate_slot_structure(bad_slot)
            >>> # Returns: (False, ["Slot has date but no specific time", "Invalid duration_minutes: 0"])
        """
        errors = []

        if "start_time" not in slot:
            errors.append("Slot missing start_time")
            return False, errors

        try:
            dt = datetime.fromisoformat(slot["start_time"])
            # Reject date-only timestamps (00:00:00 suggests no time specified)
            # This catches cases where LLM extracts date but no specific time
            if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                errors.append("Slot has date but no specific time")
        except (ValueError, AttributeError) as e:
            errors.append(f"Invalid ISO 8601 start_time: {e}")
            return False, errors

        duration = slot.get("duration_minutes")
        # Allow duration_minutes: 0 or None as valid placeholder
        # FSM will sync correct duration after transition via calculate_service_durations()
        if duration is not None and (not isinstance(duration, int) or duration < 0):
            errors.append(f"Invalid duration_minutes: {duration}")

        # Return final validation result
        if errors:
            return False, errors
        return True, []

    async def _load_customer_name(self, customer_id: str) -> dict[str, Any] | None:
        """
        Load customer first_name and last_name from database.

        Args:
            customer_id: Customer UUID as string

        Returns:
            Dict with {"first_name": str, "last_name": str | None} or None if not found
        """
        from database.connection import get_async_session
        from database.models import Customer
        from sqlalchemy import select
        from uuid import UUID

        try:
            async with get_async_session() as session:
                stmt = select(Customer).where(Customer.id == UUID(customer_id))
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()

                if customer:
                    return {
                        "first_name": customer.first_name,
                        "last_name": customer.last_name
                    }
                return None
        except Exception as e:
            logger.error(f"Error loading customer name: {e}", exc_info=True)
            return None

    async def _update_customer_name(
        self,
        customer_id: str,
        first_name: str,
        last_name: str | None
    ) -> bool:
        """
        Update customer first_name and last_name in database.

        Args:
            customer_id: Customer UUID as string
            first_name: New first name
            last_name: New last name (optional)

        Returns:
            True if successful, False otherwise
        """
        from database.connection import get_async_session
        from database.models import Customer
        from sqlalchemy import select
        from uuid import UUID

        try:
            async with get_async_session() as session:
                stmt = select(Customer).where(Customer.id == UUID(customer_id))
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()

                if customer:
                    customer.first_name = first_name
                    customer.last_name = last_name
                    await session.commit()
                    logger.info(
                        f"Updated customer name | id={customer_id} | name={first_name} {last_name}"
                    )
                    return True
                return False
        except Exception as e:
            logger.error(f"Error updating customer name: {e}", exc_info=True)
            return False

    async def transition(self, intent: Intent) -> FSMResult:
        """
        Execute a state transition based on intent.

        Args:
            intent: The intent triggering the transition

        Returns:
            FSMResult with success status, new state, and collected data
        """
        from agent.validators.slot_validator import SlotValidator

        from_state = self._state

        # Handle cancel from any state
        if intent.type == IntentType.CANCEL_BOOKING:
            self._state = BookingState.IDLE
            self._collected_data = {}
            self._last_updated = datetime.now(UTC)

            logger.info(
                "FSM transition: %s -> %s | intent=%s | conversation_id=%s",
                from_state.value,
                self._state.value,
                intent.type.value,
                self._conversation_id,
            )

            return FSMResult(
                success=True,
                new_state=self._state,
                collected_data=self._collected_data.copy(),
                next_action="booking_cancelled",
                validation_errors=[],
            )

        # Validate transition
        if not self.can_transition(intent):
            validation_errors = self._get_validation_errors(intent)

            logger.warning(
                "FSM transition rejected: %s -> ? | intent=%s | errors=%s | conversation_id=%s",
                from_state.value,
                intent.type.value,
                validation_errors,
                self._conversation_id,
            )

            return FSMResult(
                success=False,
                new_state=self._state,
                collected_data=self._collected_data.copy(),
                next_action="invalid_transition",
                validation_errors=validation_errors,
            )

        # v4.2: Handle CONFIRM_STYLIST_CHANGE intent
        # This is triggered when user confirms they want to book with a different stylist
        if (
            self._state == BookingState.SLOT_SELECTION
            and intent.type == IntentType.CONFIRM_STYLIST_CHANGE
        ):
            # Apply the pending stylist change
            pending_slot = self._collected_data.get("pending_slot")
            pending_stylist_id = self._collected_data.get("pending_stylist_id")
            pending_stylist_name = self._collected_data.get("pending_stylist_name")

            if pending_slot and pending_stylist_id:
                # Update stylist to the new one and set the slot
                self._collected_data["stylist_id"] = pending_stylist_id
                self._collected_data["stylist_name"] = pending_stylist_name
                self._collected_data["slot"] = pending_slot
                # Clear pending flags
                self._collected_data.pop("pending_stylist_change", None)
                self._collected_data.pop("pending_slot", None)
                self._collected_data.pop("pending_stylist_id", None)
                self._collected_data.pop("pending_stylist_name", None)
                logger.info(
                    f"Stylist change confirmed | new_stylist={pending_stylist_name} | "
                    f"conversation_id={self._conversation_id}"
                )
            # Transition will continue to CUSTOMER_DATA as defined in TRANSITIONS

        # SLOT VALIDATION: Centralized validation via SlotValidator
        # This checks structure, closed days, and 3-day rule
        if (
            self._state == BookingState.SLOT_SELECTION
            and intent.type == IntentType.SELECT_SLOT
        ):
            slot = intent.entities.get("slot", self._collected_data.get("slot"))
            if slot:
                # Resolve slot_time to full start_time using slots_shown context
                # This handles "a las 10:30" where LLM only extracts the time
                if "slot_time" in slot and "start_time" not in slot:
                    slot_time = slot["slot_time"]
                    slots_shown = self._collected_data.get("slots_shown", [])
                    resolved = False
                    for shown_slot in slots_shown:
                        if shown_slot.get("time") == slot_time:
                            slot["start_time"] = shown_slot.get("full_datetime")
                            slot.pop("slot_time", None)
                            resolved = True
                            logger.info(
                                f"Resolved slot_time '{slot_time}' to start_time '{slot['start_time']}' "
                                f"from slots_shown | conversation_id={self._conversation_id}"
                            )
                            break
                    if not resolved:
                        logger.warning(
                            f"Could not resolve slot_time '{slot_time}' against slots_shown "
                            f"(available times: {[s.get('time') for s in slots_shown]}) | "
                            f"conversation_id={self._conversation_id}"
                        )
                    # Update entities with resolved slot
                    intent.entities["slot"] = slot

                # v4.2: Check if this slot is from soonest_any with different stylist
                # If so, require confirmation before proceeding
                slot_stylist_id = slot.get("stylist_id")
                current_stylist_id = str(self._collected_data.get("stylist_id", ""))
                is_from_soonest_any = slot.get("is_soonest_any", False)

                if slot_stylist_id and current_stylist_id and slot_stylist_id != current_stylist_id:
                    # User selected a slot with a different stylist
                    self._collected_data["pending_stylist_change"] = True
                    self._collected_data["pending_slot"] = slot
                    self._collected_data["pending_stylist_id"] = slot_stylist_id
                    self._collected_data["pending_stylist_name"] = slot.get("stylist_name") or slot.get("stylist")
                    logger.info(
                        f"Stylist change detected | current={current_stylist_id} | "
                        f"new={slot_stylist_id} | name={slot.get('stylist_name')} | "
                        f"conversation_id={self._conversation_id}"
                    )
                    # Return success but stay in SLOT_SELECTION to ask for confirmation
                    return FSMResult(
                        success=True,
                        new_state=BookingState.SLOT_SELECTION,
                        collected_data=self._collected_data.copy(),
                        next_action="confirm_stylist_change",
                        validation_errors=[],
                    )

                # Async validation against DB rules
                validation = await SlotValidator.validate_complete(slot)

                if not validation.valid:
                    logger.warning(
                        "FSM slot validation failed: %s -> CUSTOMER_DATA | error=%s | conversation_id=%s",
                        self._state.value,
                        validation.error_message,
                        self._conversation_id,
                    )
                    return FSMResult(
                        success=False,
                        new_state=self._state,
                        collected_data=self._collected_data.copy(),
                        next_action="invalid_transition",
                        validation_errors=[validation.error_message or "Slot inválido"],
                    )

        # Get target state
        to_state = self.TRANSITIONS[self._state][intent.type]

        # Update collected data from intent entities
        self._merge_entities(intent.entities)

        # SLOT_SELECTION: Mark date preference requested when CHECK_AVAILABILITY intent
        if (
            from_state == BookingState.SLOT_SELECTION
            and intent.type == IntentType.CHECK_AVAILABILITY
            and to_state == BookingState.SLOT_SELECTION  # Self-loop
        ):
            self._collected_data["date_preference_requested"] = True
            logger.info(
                "Date preference received in SLOT_SELECTION, marking flag",
                extra={"conversation_id": self._conversation_id}
            )

        # CUSTOMER_DATA: Enhanced 3-phase logic with customer name confirmation (v6.0)
        # Phase 1a: Ask who the appointment is for
        # Phase 1b: Confirm customer name (if use_customer_name=True)
        # Phase 1c: Request third-party name (if needed)
        # Phase 2: Collect notes
        # Only advance to CONFIRMATION when both name and notes are complete
        if from_state == BookingState.CUSTOMER_DATA:
            # Get phase tracking variables
            has_appointee_name = bool(self._collected_data.get("first_name"))
            use_customer_name = self._collected_data.get("use_customer_name", False)
            name_confirmation_pending = self._collected_data.get("name_confirmation_pending", False)
            appointee_name_confirmed = self._collected_data.get("appointee_name_confirmed", False)
            notes_asked = self._collected_data.get("notes_asked", False)

            # Sub-phase 1a: USE_CUSTOMER_NAME intent (user said "sí"/"para mí")
            if intent.type == IntentType.USE_CUSTOMER_NAME and not use_customer_name:
                # Load customer name from DB
                customer_id = self._collected_data.get("customer_id")
                if customer_id:
                    customer_data = await self._load_customer_name(customer_id)
                    if customer_data:
                        self._collected_data["customer_first_name"] = customer_data["first_name"]
                        self._collected_data["customer_last_name"] = customer_data.get("last_name")
                        self._collected_data["use_customer_name"] = True
                        self._collected_data["name_confirmation_pending"] = True
                        logger.info(
                            f"Loaded customer name from DB | name={customer_data['first_name']}",
                            extra={"conversation_id": self._conversation_id}
                        )
                    else:
                        # Fallback: DB load failed, ask for name manually
                        self._collected_data["use_customer_name"] = False
                        logger.warning("Failed to load customer name, falling back to manual entry")
                to_state = BookingState.CUSTOMER_DATA  # Self-loop

            # Sub-phase 1b: CONFIRM_NAME intent (user confirmed shown name)
            elif intent.type == IntentType.CONFIRM_NAME and name_confirmation_pending:
                # Use customer name for appointment
                self._collected_data["first_name"] = self._collected_data["customer_first_name"]
                self._collected_data["last_name"] = self._collected_data.get("customer_last_name")
                self._collected_data["appointee_name_confirmed"] = True
                self._collected_data["name_confirmation_pending"] = False
                logger.info(
                    f"Customer confirmed name | name={self._collected_data['first_name']}",
                    extra={"conversation_id": self._conversation_id}
                )
                to_state = BookingState.CUSTOMER_DATA  # Self-loop

            # Sub-phase 1b: CORRECT_NAME intent (user corrected their name)
            elif intent.type == IntentType.CORRECT_NAME and name_confirmation_pending:
                # Extract corrected name from intent
                new_first_name = intent.entities.get("first_name")
                new_last_name = intent.entities.get("last_name")

                if new_first_name:
                    # Use corrected name for appointment
                    self._collected_data["first_name"] = new_first_name
                    self._collected_data["last_name"] = new_last_name
                    self._collected_data["appointee_name_confirmed"] = True
                    self._collected_data["name_confirmation_pending"] = False

                    # Update customer record in DB
                    customer_id = self._collected_data.get("customer_id")
                    if customer_id:
                        await self._update_customer_name(customer_id, new_first_name, new_last_name)

                    logger.info(
                        f"Customer corrected name | old={self._collected_data.get('customer_first_name')} | "
                        f"new={new_first_name}",
                        extra={"conversation_id": self._conversation_id}
                    )
                to_state = BookingState.CUSTOMER_DATA  # Self-loop

            # Sub-phase 1c: PROVIDE_THIRD_PARTY_BOOKING (third party without name)
            elif intent.type == IntentType.PROVIDE_THIRD_PARTY_BOOKING:
                # Just mark that we need to ask for third party name
                # The next PROVIDE_CUSTOMER_DATA will have the name
                self._collected_data["use_customer_name"] = False
                logger.info(
                    "Third-party booking without name, will ask for name",
                    extra={"conversation_id": self._conversation_id}
                )
                to_state = BookingState.CUSTOMER_DATA  # Self-loop

            # Sub-phase 2: PROVIDE_CUSTOMER_DATA (name directly provided or notes)
            elif intent.type == IntentType.PROVIDE_CUSTOMER_DATA:
                # Check if this is providing name or notes based on context
                has_first_name_in_intent = bool(intent.entities.get("first_name"))

                if has_first_name_in_intent and not has_appointee_name:
                    # This is providing name (either initial or after third_party_booking)
                    self._collected_data["appointee_name_confirmed"] = True
                    self._collected_data["use_customer_name"] = False
                    logger.info(
                        f"Name provided directly | name={intent.entities.get('first_name')}",
                        extra={"conversation_id": self._conversation_id}
                    )

                # Standard logic: advance if both name and notes collected
                has_name = bool(self._collected_data.get("first_name"))
                notes_asked = self._collected_data.get("notes_asked", False)

                if has_name and notes_asked:
                    # Both phases complete - advance to CONFIRMATION
                    to_state = BookingState.CONFIRMATION
                    logger.info(
                        "CUSTOMER_DATA phases complete -> CONFIRMATION",
                        extra={"conversation_id": self._conversation_id}
                    )
                else:
                    to_state = BookingState.CUSTOMER_DATA  # Self-loop

        # Reset date_preference_requested when entering SLOT_SELECTION from STYLIST_SELECTION
        if (
            from_state == BookingState.STYLIST_SELECTION
            and to_state == BookingState.SLOT_SELECTION
        ):
            self._collected_data["date_preference_requested"] = False
            logger.info(
                "Entering SLOT_SELECTION, resetting date_preference_requested flag",
                extra={"conversation_id": self._conversation_id}
            )

        # Reset collected_data when starting new booking from BOOKED state
        # Preserve customer_id for continuity, clear all other booking data
        if (
            from_state == BookingState.BOOKED
            and intent.type == IntentType.START_BOOKING
            and to_state == BookingState.SERVICE_SELECTION
        ):
            customer_id = self._collected_data.get("customer_id")
            self._collected_data = {"customer_id": customer_id} if customer_id else {}
            logger.info(
                "FSM reset for new booking from BOOKED | preserving customer_id=%s",
                customer_id,
                extra={"conversation_id": self._conversation_id}
            )

        # Update state
        self._state = to_state
        self._last_updated = datetime.now(UTC)

        # NOTE: Auto-reset removed. The FSM stays in BOOKED state until
        # book() executes successfully, then conversational_agent calls fsm.reset()
        # This ensures collected_data is available for the booking tool.

        # Determine next action
        next_action = self._get_next_action()

        logger.info(
            "FSM transition: %s -> %s | intent=%s | conversation_id=%s",
            from_state.value,
            self._state.value,
            intent.type.value,
            self._conversation_id,
        )

        return FSMResult(
            success=True,
            new_state=self._state,
            collected_data=self._collected_data.copy(),
            next_action=next_action,
            validation_errors=[],
        )

    def reset(self) -> None:
        """Reset FSM to initial state, clearing all collected data."""
        from_state = self._state
        self._state = BookingState.IDLE
        self._collected_data = {}
        self._last_updated = datetime.now(UTC)

        logger.info(
            "FSM reset: %s -> %s | conversation_id=%s",
            from_state.value,
            self._state.value,
            self._conversation_id,
        )

    async def calculate_service_durations(self) -> None:
        """
        Calculate and update service durations from database.

        This method:
        1. Resolves each service name to a UUID using service_resolver (consistent with search)
        2. Fetches duration from database
        3. Updates service_details with enriched service data
        4. Calculates total_duration_minutes
        5. Synchronizes slot.duration_minutes

        Should be called after services are confirmed.
        """
        from agent.utils.service_resolver import resolve_single_service
        from database.connection import get_async_session
        from database.models import Service
        from sqlalchemy import select

        services = self._collected_data.get("services", [])
        if not services:
            logger.debug("No services to calculate duration for")
            return

        service_details: list[ServiceDetail] = []
        total_duration = 0

        try:
            async with get_async_session() as session:
                for service_name in services:
                    try:
                        # Resolve service name to UUID or ambiguity info
                        result = await resolve_single_service(service_name)
                        
                        service_model = None
                        
                        if isinstance(result, dict):
                            # Ambiguity info returned
                            # In this context (calculating duration for already selected services),
                            # we pick the first option as the "best guess" to avoid blocking.
                            # The user likely selected one of these.
                            options = result.get("options", [])
                            if options:
                                first_option = options[0]
                                # We have the details in the option dict, no need to query DB if complete
                                # But let's query DB by ID to be safe and consistent
                                service_uuid = first_option.get("id")
                                logger.info(
                                    f"Ambiguous service '{service_name}', defaulting to first option: {first_option.get('name')}"
                                )
                                # Fetch by UUID
                                if service_uuid:
                                    query = select(Service).where(Service.id == service_uuid)
                                    db_result = await session.execute(query)
                                    service_model = db_result.scalar_one_or_none()
                        else:
                            # UUID returned (unambiguous)
                            service_uuid = result
                            query = select(Service).where(Service.id == service_uuid)
                            db_result = await session.execute(query)
                            service_model = db_result.scalar_one_or_none()

                        if service_model:
                            service_details.append(
                                ServiceDetail(name=service_model.name, duration_minutes=service_model.duration_minutes)
                            )
                            total_duration += service_model.duration_minutes
                            logger.debug(
                                f"Service '{service_name}' resolved to '{service_model.name}': {service_model.duration_minutes}min"
                            )
                        else:
                            # UUID valid but not found in DB? Should not happen.
                            logger.warning(f"Service UUID found but DB record missing for '{service_name}'")
                            service_details.append(
                                ServiceDetail(name=service_name, duration_minutes=60)
                            )
                            total_duration += 60

                    except Exception as e:
                        # resolve_single_service raises ValueError if not found
                        logger.warning(f"Could not resolve service '{service_name}': {e}. Using default 60min.")
                        service_details.append(
                            ServiceDetail(name=service_name, duration_minutes=60)
                        )
                        total_duration += 60

            # Update collected_data with enriched service data
            self._collected_data["service_details"] = service_details
            self._collected_data["total_duration_minutes"] = total_duration

            # Synchronize slot.duration_minutes if slot exists
            if "slot" in self._collected_data:
                self._collected_data["slot"]["duration_minutes"] = total_duration
                logger.info(
                    f"Slot duration synchronized: {total_duration}min | services={len(services)}"
                )

            logger.info(
                "Service durations calculated | total=%dmin | services=%s | conversation_id=%s",
                total_duration,
                [s["name"] for s in service_details],
                self._conversation_id,
            )

        except Exception as e:
            logger.error(
                f"Failed to calculate service durations: {e}",
                exc_info=True,
                extra={"conversation_id": self._conversation_id}
            )
            # On error, set a conservative default
            self._collected_data["total_duration_minutes"] = 60 * len(services)
            if "slot" in self._collected_data:
                self._collected_data["slot"]["duration_minutes"] = 60 * len(services)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize FSM state to dictionary for checkpoint storage.

        Converts all non-JSON-serializable types (UUID, datetime, etc.)
        to their string representations.

        Returns:
            Dictionary with keys: state, collected_data, last_updated

        Example:
            >>> fsm = BookingFSM("conv-123")
            >>> fsm_dict = fsm.to_dict()
            >>> fsm_dict["state"]
            "idle"
            >>> fsm_dict["last_updated"]
            "2025-11-24T18:27:54.123456+00:00"
        """
        # Deep copy to avoid mutations
        serializable_data: dict[str, Any] = {}

        for key, value in self._collected_data.items():
            if value is None:
                serializable_data[key] = None
            elif isinstance(value, str):
                serializable_data[key] = value
            elif isinstance(value, bool):
                # Must check bool before int since bool is subclass of int
                serializable_data[key] = value
            elif isinstance(value, int):
                serializable_data[key] = value
            elif isinstance(value, list):
                # Handle lists (services, service_details)
                serializable_list = []
                for item in value:
                    if isinstance(item, dict):
                        # ServiceDetail: {name: str, duration_minutes: int}
                        serializable_list.append(item)
                    elif isinstance(item, str):
                        serializable_list.append(item)
                    else:
                        # Fallback for unknown types
                        serializable_list.append(str(item))
                serializable_data[key] = serializable_list
            elif isinstance(value, dict):
                # Handle dicts (slot, service_details elements)
                serializable_dict = {}
                for k, v in value.items():
                    if isinstance(v, str):
                        serializable_dict[k] = v
                    elif isinstance(v, (int, bool, type(None))):
                        serializable_dict[k] = v
                    else:
                        # Convert other types to string
                        serializable_dict[k] = str(v)
                serializable_data[key] = serializable_dict
            else:
                # Fallback for unknown types (convert to string)
                serializable_data[key] = str(value)

        return {
            "state": self._state.value,
            "collected_data": serializable_data,
            "last_updated": self._last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, conversation_id: str, data: dict[str, Any]) -> "BookingFSM":
        """
        Deserialize FSM state from dictionary (checkpoint storage).

        This is the new primary way to load FSM state from ConversationState.
        Replaces the Redis-based load() method for the single-source-of-truth architecture.

        Args:
            conversation_id: Unique identifier for the conversation
            data: Dictionary with keys: state, collected_data, last_updated

        Returns:
            BookingFSM instance with restored state, or IDLE if data is invalid

        Error Handling:
            - Invalid state enum: fallback to IDLE
            - Missing fields: use defaults (empty dict for collected_data)
            - Malformed datetime: log warning, use current time
            - Slot validation failure: clean slot, reset to SLOT_SELECTION

        Example:
            >>> data = {
            ...     "state": "slot_selection",
            ...     "collected_data": {"services": ["Corte"]},
            ...     "last_updated": "2025-11-24T18:27:54.123456+00:00"
            ... }
            >>> fsm = BookingFSM.from_dict("conv-123", data)
            >>> fsm.state
            BookingState.SLOT_SELECTION
        """
        fsm = cls(conversation_id)

        # Handle empty data
        if not data:
            logger.debug(
                "FSM from_dict: empty data, creating new IDLE FSM | conversation_id=%s",
                conversation_id,
            )
            return fsm

        try:
            # Deserialize state (with fallback to IDLE on error)
            state_value = data.get("state")
            if state_value:
                try:
                    fsm._state = BookingState(state_value)
                except ValueError:
                    logger.error(
                        "FSM from_dict: invalid state value, falling back to IDLE | "
                        "conversation_id=%s | state=%s",
                        conversation_id,
                        state_value,
                    )
                    fsm._state = BookingState.IDLE

            # Deserialize collected_data
            fsm._collected_data = data.get("collected_data", {})
            if not isinstance(fsm._collected_data, dict):
                logger.warning(
                    "FSM from_dict: collected_data is not dict, using empty dict | "
                    "conversation_id=%s | type=%s",
                    conversation_id,
                    type(fsm._collected_data),
                )
                fsm._collected_data = {}

            # Deserialize last_updated
            if "last_updated" in data:
                try:
                    fsm._last_updated = datetime.fromisoformat(data["last_updated"])
                except (ValueError, TypeError):
                    logger.warning(
                        "FSM from_dict: failed to parse last_updated, using current time | "
                        "conversation_id=%s | value=%s",
                        conversation_id,
                        data.get("last_updated"),
                    )
                    fsm._last_updated = datetime.now(UTC)

            # ================================================================
            # VALIDATE SLOT FRESHNESS (ADR-008: Obsolete slot cleanup)
            # ================================================================
            # Ensure slot is still valid after deserialization
            fsm._validate_and_clean_slot()

            logger.debug(
                "FSM from_dict: deserialized state=%s | conversation_id=%s",
                fsm._state.value,
                conversation_id,
            )

            return fsm

        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(
                "FSM from_dict: unexpected error during deserialization, "
                "falling back to IDLE | conversation_id=%s | error=%s",
                conversation_id,
                str(e),
            )
            return cls(conversation_id)

    def _merge_entities(self, entities: dict[str, Any]) -> None:
        """
        Merge intent entities into collected data.

        Special handling:
        - services list: accumulate rather than replace
        - CUSTOMER_DATA phase: FSM internally tracks notes_asked flag
        """
        # ================================================================
        # CUSTOMER_DATA PHASE TRACKING (Fix for Bug #1)
        # ================================================================
        # The FSM internally manages notes_asked flag based on conversation phase:
        # - Phase 1: User provides name → save first_name, notes_asked stays false
        # - Phase 2: User responds to notes question → set notes_asked=true
        #
        # We do NOT trust notes_asked from intent extractor because LLM may
        # incorrectly set it when only name was provided.
        # ================================================================
        if self._state == BookingState.CUSTOMER_DATA:
            # Ignore notes_asked from intent extractor - FSM manages this internally
            entities = {k: v for k, v in entities.items() if k != "notes_asked"}

            has_existing_name = bool(self._collected_data.get("first_name"))
            incoming_name = entities.get("first_name")

            if not has_existing_name and incoming_name:
                # Phase 1: First time receiving name - don't set notes_asked yet
                logger.info(
                    "CUSTOMER_DATA Phase 1: Name received (%s), notes_asked stays false",
                    incoming_name,
                )
            elif has_existing_name:
                # Phase 2: We already have name, this is response to notes question
                # Set notes_asked=true (regardless of whether actual notes were provided)
                self._collected_data["notes_asked"] = True
                logger.info(
                    "CUSTOMER_DATA Phase 2: Notes response received, notes_asked=true | notes=%s",
                    entities.get("notes", "none"),
                )

        # Standard entity merging
        for key, value in entities.items():
            if key == "services" and isinstance(value, list):
                # Accumulate services, avoiding duplicates and empty strings
                existing = self._collected_data.get("services", [])
                for service in value:
                    # Filter empty strings and whitespace-only strings
                    if service and service.strip() and service.strip() not in existing:
                        existing.append(service.strip())
                        logger.debug(f"Added service: '{service.strip()}'")
                    elif not service or not service.strip():
                        logger.warning(f"Filtered empty service name: '{service}'")
                self._collected_data["services"] = existing
            else:
                self._collected_data[key] = value

    def _get_validation_errors(self, intent: Intent) -> list[str]:
        """Get list of validation errors for a failed transition."""
        errors: list[str] = []

        # Check if transition exists
        valid_transitions = self.TRANSITIONS.get(self._state, {})
        if intent.type not in valid_transitions:
            errors.append(
                f"Transition '{intent.type.value}' not allowed from state '{self._state.value}'"
            )
            return errors

        # Check data requirements
        requirements = self.TRANSITION_REQUIREMENTS.get((self._state, intent.type), [])
        merged_data = {**self._collected_data, **intent.entities}

        for required_field in requirements:
            value = merged_data.get(required_field)
            if value is None:
                errors.append(f"Missing required field: '{required_field}'")
            elif isinstance(value, (list, str)) and len(value) == 0:
                errors.append(f"Empty required field: '{required_field}'")

        return errors

    def _get_next_action(self) -> str:
        """Determine the suggested next action based on current state."""
        next_actions: dict[BookingState, str] = {
            BookingState.IDLE: "greet_or_start_booking",
            BookingState.SERVICE_SELECTION: "show_services",
            BookingState.STYLIST_SELECTION: "show_stylists",
            BookingState.SLOT_SELECTION: "show_available_slots",
            BookingState.CUSTOMER_DATA: "collect_customer_info",
            BookingState.CONFIRMATION: "show_booking_summary",
            BookingState.BOOKED: "confirm_booking_created",
        }
        return next_actions.get(self._state, "unknown_action")

    def get_response_guidance(self) -> ResponseGuidance:
        """
        Generate proactive guidance for LLM based on current FSM state (Story 5-7b).

        Returns guidance that instructs the LLM what it MUST show, MUST ask,
        and MUST NOT mention based on the current booking flow state.

        Returns:
            ResponseGuidance with must_show, must_ask, forbidden, and context_hint

        Example:
            >>> fsm = BookingFSM("conv-123")
            >>> fsm._state = BookingState.SERVICE_SELECTION
            >>> guidance = fsm.get_response_guidance()
            >>> "estilistas" in guidance.forbidden
            True
        """
        import time
        start_time = time.perf_counter()

        guidance = self._GUIDANCE_MAP.get(self._state, self._DEFAULT_GUIDANCE)

        # For SERVICE_SELECTION, customize must_show based on whether services are selected
        if self._state == BookingState.SERVICE_SELECTION:
            services = self._collected_data.get("services", [])
            if services:
                # Services already selected - ask about adding more or confirming
                # Bug #3 fix: Explicit forbidden list to prevent showing stylists
                guidance = ResponseGuidance(
                    must_show=[f"servicios seleccionados: {', '.join(services)}"],
                    must_ask="¿Deseas agregar otro servicio o continuamos con estos?",
                    forbidden=[
                        "estilistas", "Ana", "María", "Carlos", "Pilar", "Laura",
                        "horarios", "disponibilidad", "hora",
                        "confirmación de cita", "reserva confirmada",
                    ],
                    context_hint=(
                        "Usuario tiene servicios seleccionados. "
                        "Pregunta si quiere agregar más o confirmar. "
                        "NO muestres estilistas hasta que confirme servicios."
                    ),
                    required_tool_call="search_services",  # Still required for adding more
                )
            else:
                # No services yet - MUST call search_services before any confirmation
                guidance = ResponseGuidance(
                    must_show=["lista de servicios disponibles"],
                    must_ask="¿Qué servicio te gustaría?",
                    forbidden=[
                        "estilistas", "Ana", "María", "Carlos", "Pilar", "Laura",
                        "horarios", "disponibilidad", "hora",
                        "confirmación de cita", "reserva confirmada",
                        # NEW: Prohibit premature service confirmation
                        "has seleccionado", "servicio seleccionado",
                    ],
                    context_hint=(
                        "Usuario está seleccionando servicios. "
                        "OBLIGATORIO: Llama search_services ANTES de confirmar cualquier servicio. "
                        "NO confirmes servicios sin verificar que existen en la BD."
                    ),
                    required_tool_call="search_services",  # MUST call before confirming
                )

        # For CUSTOMER_DATA, customize based on enhanced 3-phase flow (v6.0)
        elif self._state == BookingState.CUSTOMER_DATA:
            # Get phase tracking variables
            has_appointee_name = bool(self._collected_data.get("first_name"))
            use_customer_name = self._collected_data.get("use_customer_name", False)
            name_confirmation_pending = self._collected_data.get("name_confirmation_pending", False)
            appointee_name_confirmed = self._collected_data.get("appointee_name_confirmed", False)
            notes_asked = self._collected_data.get("notes_asked", False)

            # Sub-phase 1a: Ask who the appointment is for
            if not has_appointee_name and not use_customer_name and not name_confirmation_pending:
                guidance = ResponseGuidance(
                    must_show=[],
                    must_ask="¿Para quién es la cita? ¿Uso tu nombre?",
                    forbidden=["confirmación", "resumen", "notas"],
                    context_hint="Preguntar si la cita es para el usuario o para otra persona. Esperar respuesta: 'sí'/'para mí' o nombre directo.",
                )

            # Sub-phase 1b: Confirm customer name (if use_customer_name=True)
            elif name_confirmation_pending and not appointee_name_confirmed:
                customer_first_name = self._collected_data.get("customer_first_name", "")
                customer_last_name = self._collected_data.get("customer_last_name", "")
                full_name = f"{customer_first_name} {customer_last_name}".strip()

                guidance = ResponseGuidance(
                    must_show=[f"nombre a confirmar: {full_name}"],
                    must_ask=f"Perfecto, la cita será a nombre de {full_name}. ¿Es correcto?",
                    forbidden=["confirmación de cita", "resumen", "notas"],
                    context_hint=f"Confirmar nombre del customer: {full_name}. Esperar 'sí' o corrección.",
                )

            # Sub-phase 1c: Ask for third-party name (if needed)
            elif not has_appointee_name and use_customer_name == False and not name_confirmation_pending:
                # This means user said "para otra persona" without giving name
                guidance = ResponseGuidance(
                    must_show=[],
                    must_ask="¿Cuál es el nombre de la persona?",
                    forbidden=["confirmación", "resumen", "notas"],
                    context_hint="Usuario indicó tercero pero no dio nombre. Preguntar explícitamente.",
                )

            # Sub-phase 2: Ask for notes (after name is confirmed)
            elif has_appointee_name and not notes_asked:
                first_name = self._collected_data.get("first_name")
                guidance = ResponseGuidance(
                    must_show=[],
                    must_ask="¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.) Si no, simplemente di 'no'.",
                    forbidden=["confirmación de cita", "reserva confirmada", "resumen de cita"],
                    context_hint=f"Ya tenemos nombre: {first_name}. Ahora preguntar por notas/preferencias.",
                )

            else:
                # Edge case: both collected (shouldn't happen if FSM transitions correctly)
                guidance = ResponseGuidance(
                    must_show=["resumen de la cita"],
                    must_ask="¿Confirmas la reserva?",
                    forbidden=[],
                    context_hint="Datos del cliente completos. Mostrar resumen y confirmar.",
                )

        # For SLOT_SELECTION, customize based on whether date preference requested
        elif self._state == BookingState.SLOT_SELECTION:
            date_requested = self._collected_data.get("date_preference_requested", False)

            if not date_requested:
                # Sub-fase 1: Preguntar por fecha
                guidance = ResponseGuidance(
                    must_show=[],
                    must_ask="¿Para qué día te gustaría la cita? (ej: mañana, el viernes, el 1 de diciembre, o lo antes posible)",
                    forbidden=["horarios", "10:00", "14:30", "disponibilidad específica"],
                    context_hint="IMPORTANTE: PREGUNTAR por preferencia temporal. NO buscar horarios aún.",
                )
            else:
                # Sub-fase 2: Mostrar horarios (después de tener preferencia)
                guidance = ResponseGuidance(
                    must_show=["horarios disponibles del estilista"],
                    must_ask="¿Qué horario te viene mejor?",
                    forbidden=["confirmación de cita"],
                    context_hint="Usuario ya dio preferencia temporal. Mostrar horarios disponibles.",
                )

        # Log guidance generation metrics (AC #8)
        generation_time_ms = (time.perf_counter() - start_time) * 1000
        self._log_guidance_generated(guidance, generation_time_ms)

        return guidance

    def _log_guidance_generated(
        self,
        guidance: ResponseGuidance,
        generation_time_ms: float,
    ) -> None:
        """
        Log guidance generation with FSM context (AC #8).

        Args:
            guidance: Generated ResponseGuidance
            generation_time_ms: Time taken to generate guidance
        """
        logger.info(
            "Guidance generated | state=%s | forbidden=%s | must_ask=%s | time=%.2fms",
            self._state.value,
            guidance.forbidden[:3] if guidance.forbidden else [],
            guidance.must_ask[:50] if guidance.must_ask else None,
            generation_time_ms,
            extra={
                "fsm_state": self._state.value,
                "conversation_id": self._conversation_id,
                "forbidden_count": len(guidance.forbidden),
                "must_show_count": len(guidance.must_show),
                "has_must_ask": guidance.must_ask is not None,
                "generation_time_ms": round(generation_time_ms, 2),
            }
        )

    def _validate_and_clean_slot(self) -> None:
        """
        Validate that the selected slot is still valid (fresh).

        If a slot is obsolete (past date or violates 3-day minimum rule),
        clean it up and reset FSM to SLOT_SELECTION state.

        This prevents silent booking failures when users resume old conversations
        with expired/obsolete slots.

        Implementation of ADR-008: Obsolete Slot Cleanup

        Side effects:
        - If slot is invalid: clears slot, resets state to SLOT_SELECTION
        - Logs WARNING if slot was cleaned
        """
        if not self._collected_data.get("slot"):
            # No slot selected yet - nothing to validate
            return

        slot = self._collected_data["slot"]
        start_time_str = slot.get("start_time")

        if not start_time_str:
            # Malformed slot - clean it up
            logger.warning(
                "Slot validation: malformed slot detected (missing start_time) | "
                "conversation_id=%s",
                self._conversation_id,
            )
            self._collected_data.pop("slot", None)
            return

        try:
            # Parse the start_time (ISO 8601 with timezone)
            slot_datetime = datetime.fromisoformat(start_time_str)

            # Get current time in UTC for comparison
            now = datetime.now(UTC)

            # Calculate days until appointment
            days_until = (slot_datetime - now).days

            # Validate 3-day minimum rule
            if days_until < 3:
                logger.warning(
                    "Slot validation: 3-day rule violation | "
                    "conversation_id=%s | days_until=%d | min_required=3 | "
                    "slot_date=%s",
                    self._conversation_id,
                    days_until,
                    slot_datetime.isoformat(),
                )
                # Clean up the obsolete slot
                self._collected_data.pop("slot", None)

                # Reset to SLOT_SELECTION so user must choose a new date
                if self._state not in [BookingState.IDLE, BookingState.SERVICE_SELECTION, BookingState.STYLIST_SELECTION]:
                    self._state = BookingState.SLOT_SELECTION

        except (ValueError, TypeError) as e:
            logger.warning(
                "Slot validation: failed to parse start_time | "
                "conversation_id=%s | error=%s | start_time=%s",
                self._conversation_id,
                str(e),
                start_time_str,
            )
            # Malformed datetime - clean it up
            self._collected_data.pop("slot", None)

    # ============================================================================
    # GUIDANCE MAP BY STATE (Story 5-7b)
    # ============================================================================
    # Static mapping of FSM states to ResponseGuidance.
    # Aligns with FORBIDDEN_PATTERNS from ResponseValidator (Story 5-7a).

    _DEFAULT_GUIDANCE: ClassVar[ResponseGuidance] = ResponseGuidance(
        must_show=[],
        must_ask=None,
        forbidden=[],
        context_hint="Sin booking activo.",
    )

    _GUIDANCE_MAP: ClassVar[dict[BookingState, ResponseGuidance]] = {
        BookingState.IDLE: ResponseGuidance(
            must_show=[],
            must_ask=None,
            forbidden=[],
            context_hint="Sin booking activo. Responde a consultas generales o inicia booking.",
        ),
        BookingState.SERVICE_SELECTION: ResponseGuidance(
            # Customized dynamically in get_response_guidance()
            must_show=["lista de servicios disponibles"],
            must_ask="¿Qué servicio te gustaría?",
            forbidden=[
                "estilistas", "Ana", "María", "Carlos", "Pilar", "Laura",  # Stylist names
                "horarios", "disponibilidad", "hora", "10:00", "11:00",  # Time slots
                "confirmación de cita", "reserva confirmada",
            ],
            context_hint="Usuario está seleccionando servicios. NO mostrar estilistas ni horarios.",
        ),
        BookingState.STYLIST_SELECTION: ResponseGuidance(
            must_show=["lista de estilistas disponibles"],
            must_ask="¿Con quién te gustaría la cita?",
            forbidden=["horarios específicos", "datos del cliente", "confirmación de cita"],
            context_hint="Usuario debe elegir estilista. NO mostrar horarios aún.",
        ),
        BookingState.SLOT_SELECTION: ResponseGuidance(
            must_show=["horarios disponibles del estilista"],
            must_ask="¿Qué horario te viene mejor?",
            forbidden=["confirmación de cita", "solicitud de datos adicionales"],
            context_hint="Usuario debe elegir horario. NO confirmar cita aún.",
        ),
        BookingState.CUSTOMER_DATA: ResponseGuidance(
            must_show=[],
            must_ask="¿Me puedes dar tu nombre para la reserva?",
            forbidden=["confirmación de cita sin datos"],
            context_hint="Recopilar datos del cliente antes de confirmar.",
        ),
        BookingState.CONFIRMATION: ResponseGuidance(
            must_show=["resumen de la cita"],
            must_ask="¿Confirmas la reserva?",
            forbidden=[],
            context_hint="Mostrar resumen y esperar confirmación del usuario.",
        ),
        BookingState.BOOKED: ResponseGuidance(
            must_show=["confirmación de cita creada"],
            must_ask=None,
            forbidden=[],
            context_hint="Booking completado. Confirmar cita y ofrecer ayuda adicional.",
        ),
    }

    # ============================================================================
    # V5.0 PRESCRIPTIVE FSM ARCHITECTURE
    # ============================================================================
    # Methods for prescriptive action generation (v5.0 architecture).
    # FSM prescribes EXACT tools to call + response templates.
    # LLM relegated to: (1) intent extraction (NLU), (2) response formatting (generation)

    def get_required_action(self) -> FSMAction:
        """
        Get prescriptive action for current state (v5.0 prescriptive architecture).

        This method determines EXACTLY what the agent should do based on FSM state,
        removing tool decision power from the LLM. The FSM prescribes:
        - Which tools to call (if any)
        - Tool arguments (built from collected_data)
        - Response template structure
        - Whether to allow LLM creativity in formatting

        Returns:
            FSMAction specifying tool calls and/or response generation

        Example:
            >>> fsm = BookingFSM("conv-123")
            >>> fsm._state = BookingState.SLOT_SELECTION
            >>> fsm._collected_data = {"stylist_id": "uuid-123", "total_duration_minutes": 60}
            >>> action = fsm.get_required_action()
            >>> action.action_type
            ActionType.CALL_TOOLS_SEQUENCE
            >>> action.tool_calls[0].name
            'find_next_available'
        """
        # Map states to action builders
        action_builders = {
            BookingState.IDLE: self._action_idle,
            BookingState.SERVICE_SELECTION: self._action_service_selection,
            BookingState.STYLIST_SELECTION: self._action_stylist_selection,
            BookingState.SLOT_SELECTION: self._action_slot_selection,
            BookingState.CUSTOMER_DATA: self._action_customer_data,
            BookingState.CONFIRMATION: self._action_confirmation,
            BookingState.BOOKED: self._action_booked,
        }

        builder = action_builders.get(self._state)
        if not builder:
            logger.error(f"No action builder for state {self._state}")
            return FSMAction(action_type=ActionType.NO_ACTION)

        return builder()

    def _action_idle(self) -> FSMAction:
        """
        Build action for IDLE state (no active booking).

        Returns:
            FSMAction with greeting/welcome message (no tools)
        """
        return FSMAction(
            action_type=ActionType.GENERATE_RESPONSE,
            response_template=(
                "¡Hola! Soy Maite, tu asistente virtual de la Peluquería Atrévete. "
                "¿En qué puedo ayudarte hoy? Puedo ayudarte a reservar una cita, "
                "consultar nuestros servicios, horarios, o cualquier duda que tengas."
            ),
            allow_llm_creativity=True,
        )

    def _action_service_selection(self) -> FSMAction:
        """
        Build action for SERVICE_SELECTION state.

        Logic:
        - If no services selected yet → call search_services to show catalog
        - If services already selected → ask for confirmation or more

        Returns:
            FSMAction with tool call (search_services) or response generation
        """
        services = self._collected_data.get("services", [])

        if not services:
            # No services yet - MUST call search_services to show catalog
            # Use user's original message for fuzzy matching (if available)
            # This allows "quiero cortarme el pelo" to match "Corte de Caballero"
            service_query = self._collected_data.get("service_query", "servicios")
            return FSMAction(
                action_type=ActionType.CALL_TOOLS_SEQUENCE,
                tool_calls=[
                    ToolCall(
                        name="search_services",
                        args={"query": service_query, "max_results": 10},
                        required=True,
                    )
                ],
                response_template=(
                    "¡Perfecto! Estos son algunos de nuestros servicios:\n\n"
                    "{% for service in services %}"
                    "{{ loop.index }}. {{ service.name }}"
                    "{% if service.duration_minutes %} ({{ service.duration_minutes }} min){% endif %}\n"
                    "{% endfor %}\n\n"
                    "¿Cuál te gustaría? Puedes decirme el número o el nombre del servicio."
                ),
                template_vars={"services": []},  # Will be populated by tool result
                allow_llm_creativity=True,
            )
        else:
            # Services selected - confirm or ask for more
            return FSMAction(
                action_type=ActionType.GENERATE_RESPONSE,
                response_template=(
                    "Perfecto, tienes seleccionados: {{ services|join(', ') }}.\n\n"
                    "¿Quieres agregar otro servicio o continuamos con estos?"
                ),
                template_vars={"services": services},
                allow_llm_creativity=True,
            )

    def _action_stylist_selection(self) -> FSMAction:
        """
        Build action for STYLIST_SELECTION state.

        Calls list_stylists tool to get stylists from database, filtered by
        the service category selected by the user.

        Returns:
            FSMAction with tool call (list_stylists)
        """
        # Get service category from selected services (default: Peluquería/HAIRDRESSING)
        service_category = self._collected_data.get("service_category", "HAIRDRESSING")

        return FSMAction(
            action_type=ActionType.CALL_TOOLS_SEQUENCE,
            tool_calls=[
                ToolCall(
                    name="list_stylists",
                    args={"category": service_category},
                    required=True,
                )
            ],
            response_template=(
                "Nuestros estilistas disponibles son:\n\n"
                "{% for stylist in stylists %}"
                "{{ loop.index }}. {{ stylist.name }}\n"
                "{% endfor %}\n"
                "¿Con quién te gustaría la cita? Si no tienes preferencia, "
                "puedo buscar disponibilidad con cualquiera de ellos."
            ),
            allow_llm_creativity=True,
        )

    def _action_slot_selection(self) -> FSMAction:
        """
        Build action for SLOT_SELECTION state.

        Logic:
        - Check if stylist change confirmation is pending
        - Check if date preference has been requested
        - If not requested → ask for date preference (no tool)
        - If requested → call find_next_available to show slots

        v4.2 Enhancement:
        - Pass service_duration_minutes for proper slot spacing
        - Template shows 4 options: soonest_any + 3 selected stylist slots
        - Handle pending stylist change confirmation

        Returns:
            FSMAction with tool call (find_next_available) or response generation
        """
        # v4.2: Check for pending stylist change confirmation
        pending_stylist_change = self._collected_data.get("pending_stylist_change", False)
        if pending_stylist_change:
            pending_stylist_name = self._collected_data.get("pending_stylist_name", "otro estilista")
            current_stylist_name = self._collected_data.get("stylist_name", "el estilista original")
            pending_slot = self._collected_data.get("pending_slot", {})
            slot_time = pending_slot.get("time", "")
            slot_date = pending_slot.get("date", "")

            return FSMAction(
                action_type=ActionType.GENERATE_RESPONSE,
                response_template=(
                    f"El hueco más próximo es el {slot_date} a las {slot_time}, "
                    f"pero sería con {pending_stylist_name} en lugar de {current_stylist_name}.\n\n"
                    "¿Te parece bien?"
                ),
                allow_llm_creativity=True,
            )

        stylist_id = self._collected_data.get("stylist_id")
        total_duration = self._collected_data.get("total_duration_minutes", 60)

        # v4.3: Always show availability directly after stylist selection
        # (removed date_preference_requested sub-phase - user can request different dates after seeing options)
        service_category = self._collected_data.get("service_category", "Peluquería")
        # Get user's preferred date (if provided) to pass to find_next_available
        preferred_date = self._collected_data.get("date")

        return FSMAction(
            action_type=ActionType.CALL_TOOLS_SEQUENCE,
            tool_calls=[
                ToolCall(
                    name="find_next_available",
                    args={
                        "service_category": service_category,
                        "stylist_id": str(stylist_id) if stylist_id else None,
                        "max_days_to_search": 10,
                        "start_date": preferred_date,  # User's preferred date
                        "service_duration_minutes": total_duration,  # v4.2: proper slot spacing
                    },
                    required=True,
                )
            ],
            # v4.3: Template shows soonest_any first, then selected stylist slots
            # Added message at end about searching other dates
            response_template=(
                "Aquí están los horarios disponibles:\n\n"
                "{% if soonest_any %}"
                "1. ⚡ {{ soonest_any.day_name }} {{ soonest_any.date }} a las {{ soonest_any.time }} "
                "(con {{ soonest_any.stylist_name }}) - PRÓXIMO DISPONIBLE\n"
                "{% endif %}"
                "{% for slot in selected_stylist_slots %}"
                "{{ loop.index + 1 }}. {{ slot.day_name }} {{ slot.date }} a las {{ slot.time }} "
                "(con {{ slot.stylist }})\n"
                "{% endfor %}\n\n"
                "{% if soonest_any and soonest_any.is_different_stylist %}"
                "ℹ️ La opción 1 es con otro estilista. Si la eliges, te pediré confirmación.\n\n"
                "{% endif %}"
                "¿Cuál prefieres? Puedes decirme el número.\n\n"
                "Si prefieres buscar otro día que te venga mejor, solo dímelo."
            ),
            template_vars={
                "soonest_any": None,  # Will be populated by tool result
                "selected_stylist_slots": [],  # Will be populated by tool result
            },
            allow_llm_creativity=True,
        )

    def _action_customer_data(self) -> FSMAction:
        """
        Build action for CUSTOMER_DATA state.

        Logic:
        - Phase 1: If no first_name → ask for name
        - Phase 2: If has first_name but notes not asked → ask for notes
        - After phase 2, FSM will transition to CONFIRMATION

        Returns:
            FSMAction with response generation (no tools - just collecting data)
        """
        first_name = self._collected_data.get("first_name")
        notes_asked = self._collected_data.get("notes_asked", False)

        if not first_name:
            # Phase 1: Collect name and surname for booking
            return FSMAction(
                action_type=ActionType.GENERATE_RESPONSE,
                response_template="¿A qué nombre y apellidos agendo la reserva?",
                allow_llm_creativity=True,
            )
        elif not notes_asked:
            # Phase 2: Ask for notes
            return FSMAction(
                action_type=ActionType.GENERATE_RESPONSE,
                response_template=(
                    "Perfecto, {{ first_name }}. "
                    "¿Tienes alguna preferencia o nota especial para tu cita? "
                    "(Por ejemplo, alergias, preferencias de estilo, etc.). "
                    "Si no, podemos continuar."
                ),
                template_vars={"first_name": first_name},
                allow_llm_creativity=True,
            )
        else:
            # Both phases complete - transition to CONFIRMATION will happen
            # This shouldn't be reached, but provide fallback
            return FSMAction(
                action_type=ActionType.GENERATE_RESPONSE,
                response_template="Perfecto, tengo todos tus datos. Vamos a confirmar la cita.",
                allow_llm_creativity=True,
            )

    def _action_confirmation(self) -> FSMAction:
        """
        Build action for CONFIRMATION state.

        Show booking summary and ask for final confirmation.

        Returns:
            FSMAction with response generation (no tools)
        """
        services = self._collected_data.get("services", [])
        slot = self._collected_data.get("slot", {})
        first_name = self._collected_data.get("first_name", "")
        last_name = self._collected_data.get("last_name", "")
        notes = self._collected_data.get("notes", "")

        # Get stylist name (prefer slot.stylist, fallback to collected_data.stylist_name)
        stylist_name = slot.get("stylist") or self._collected_data.get("stylist_name", "Por asignar")

        # Format datetime in Spanish (Bug #5 fix)
        date_time_formatted = "Por confirmar"
        start_time_str = slot.get("full_datetime") or slot.get("start_time", "")
        if start_time_str:
            try:
                dt = datetime.fromisoformat(start_time_str)
                # Use format_date_spanish for date + add time
                date_part = format_date_spanish(dt)
                time_part = dt.strftime("%H:%M")
                date_time_formatted = f"{date_part} a las {time_part}"
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not format datetime '{start_time_str}': {e}")
                date_time_formatted = start_time_str  # Fallback to raw value

        # Build summary data
        summary_data = {
            "services": ", ".join(services),
            "stylist_name": stylist_name,
            "date_time": date_time_formatted,
            "customer_name": f"{first_name} {last_name}".strip(),
            "notes": notes or "Ninguna",
        }

        return FSMAction(
            action_type=ActionType.GENERATE_RESPONSE,
            response_template=(
                "Perfecto, aquí está el resumen de tu cita:\n\n"
                "📅 Servicios: {{ services }}\n"
                "💇 Estilista: {{ stylist_name }}\n"
                "🕐 Fecha y hora: {{ date_time }}\n"
                "👤 Nombre: {{ customer_name }}\n"
                "📝 Notas: {{ notes }}\n\n"
                "¿Confirmas la reserva?"
            ),
            template_vars=summary_data,
            allow_llm_creativity=True,
        )

    def _action_booked(self) -> FSMAction:
        """
        Build action for BOOKED state (booking confirmed).

        This state MUST call the book() tool to actually create the appointment.
        Previous docstring was WRONG - book() was never called!

        Returns:
            FSMAction with CALL_TOOLS_SEQUENCE to invoke book() tool
        """
        # Collect all booking data from FSM collected_data
        services = self._collected_data.get("services", [])
        stylist_id = self._collected_data.get("stylist_id")
        slot = self._collected_data.get("slot", {})
        first_name = self._collected_data.get("first_name", "")
        last_name = self._collected_data.get("last_name")
        notes = self._collected_data.get("notes")
        customer_id = self._collected_data.get("customer_id")
        conversation_id = self._conversation_id

        # Get start_time from slot (prefer full_datetime, fallback to start_time)
        start_time = slot.get("full_datetime") or slot.get("start_time", "")

        return FSMAction(
            action_type=ActionType.CALL_TOOLS_SEQUENCE,
            tool_calls=[
                ToolCall(
                    name="book",
                    args={
                        "customer_id": str(customer_id) if customer_id else "",
                        "first_name": first_name,
                        "last_name": last_name,
                        "notes": notes,
                        "services": services,
                        "stylist_id": str(stylist_id) if stylist_id else "",
                        "start_time": start_time,
                        "conversation_id": str(conversation_id) if conversation_id else None,
                    },
                    required=True,
                )
            ],
            response_template=(
                "✅ ¡Listo! Tu cita ha sido confirmada.\n\n"
                "📅 Fecha: {{ friendly_date }}\n"
                "💇 Estilista: {{ stylist_name }}\n"
                "✨ Servicios: {{ service_names }}\n\n"
                "📍 Dirección: {{ salon_address }}\n\n"
                "📲 Añade la cita a tu calendario:\n"
                "{{ calendar_link }}\n\n"
                "Te esperamos en la Peluquería Atrévete. "
                "Si necesitas modificar o cancelar, no dudes en escribirnos.\n\n"
                "¿Hay algo más en lo que pueda ayudarte?"
            ),
            template_vars={},  # Will be populated by flattened tool result
            allow_llm_creativity=True,
        )
