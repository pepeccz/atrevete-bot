"""
BookingFSM - Finite State Machine controller for booking flow.

This module implements the core FSM that controls the booking conversation flow.
The FSM validates state transitions and accumulates data as the user progresses
through the booking process.

Key responsibilities:
- Validate state transitions based on current state and intent
- Accumulate booking data (services, stylist, slot, customer info)
- Persist state to Redis for session continuity
- Log all transitions for debugging and monitoring
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from agent.fsm.models import BookingState, FSMResult, Intent, IntentType
from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# TTL for FSM state in Redis (15 minutes)
FSM_TTL_SECONDS: int = 900


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
    TRANSITIONS: ClassVar[dict[BookingState, dict[IntentType, BookingState]]] = {
        BookingState.IDLE: {
            IntentType.START_BOOKING: BookingState.SERVICE_SELECTION,
        },
        BookingState.SERVICE_SELECTION: {
            IntentType.CONFIRM_SERVICES: BookingState.STYLIST_SELECTION,
        },
        BookingState.STYLIST_SELECTION: {
            IntentType.SELECT_STYLIST: BookingState.SLOT_SELECTION,
        },
        BookingState.SLOT_SELECTION: {
            IntentType.SELECT_SLOT: BookingState.CUSTOMER_DATA,
        },
        BookingState.CUSTOMER_DATA: {
            IntentType.PROVIDE_CUSTOMER_DATA: BookingState.CONFIRMATION,
        },
        BookingState.CONFIRMATION: {
            IntentType.CONFIRM_BOOKING: BookingState.BOOKED,
        },
        BookingState.BOOKED: {},  # Terminal state, auto-resets to IDLE
    }

    # Data validation requirements for each transition
    TRANSITION_REQUIREMENTS: ClassVar[dict[tuple[BookingState, IntentType], list[str]]] = {
        (BookingState.SERVICE_SELECTION, IntentType.CONFIRM_SERVICES): ["services"],
        (BookingState.STYLIST_SELECTION, IntentType.SELECT_STYLIST): ["stylist_id"],
        (BookingState.SLOT_SELECTION, IntentType.SELECT_SLOT): ["slot"],
        (BookingState.CUSTOMER_DATA, IntentType.PROVIDE_CUSTOMER_DATA): ["first_name"],
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

    def transition(self, intent: Intent) -> FSMResult:
        """
        Execute a state transition based on intent.

        Args:
            intent: The intent triggering the transition

        Returns:
            FSMResult with success status, new state, and collected data
        """
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

        # Get target state
        to_state = self.TRANSITIONS[self._state][intent.type]

        # Update collected data from intent entities
        self._merge_entities(intent.entities)

        # Update state
        self._state = to_state
        self._last_updated = datetime.now(UTC)

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

    async def persist(self) -> None:
        """
        Persist FSM state to Redis.

        The state is saved with key pattern fsm:{conversation_id}
        and TTL of 900 seconds (15 minutes).
        """
        client = get_redis_client()
        key = f"fsm:{self._conversation_id}"

        data = {
            "state": self._state.value,
            "collected_data": self._collected_data,
            "last_updated": self._last_updated.isoformat(),
        }

        await client.set(key, json.dumps(data), ex=FSM_TTL_SECONDS)

        logger.debug(
            "FSM persisted: state=%s | conversation_id=%s | ttl=%d",
            self._state.value,
            self._conversation_id,
            FSM_TTL_SECONDS,
        )

    @classmethod
    async def load(cls, conversation_id: str) -> "BookingFSM":
        """
        Load FSM state from Redis.

        If no state exists for the conversation_id, returns a new FSM in IDLE state.

        Args:
            conversation_id: Unique identifier for the conversation

        Returns:
            BookingFSM instance with restored or initial state
        """
        client = get_redis_client()
        key = f"fsm:{conversation_id}"

        data_str = await client.get(key)

        if data_str is None:
            logger.debug(
                "FSM load: no existing state, creating new | conversation_id=%s",
                conversation_id,
            )
            return cls(conversation_id)

        try:
            data = json.loads(data_str)
            fsm = cls(conversation_id)
            fsm._state = BookingState(data["state"])
            fsm._collected_data = data.get("collected_data", {})

            if "last_updated" in data:
                fsm._last_updated = datetime.fromisoformat(data["last_updated"])

            logger.debug(
                "FSM load: restored state=%s | conversation_id=%s",
                fsm._state.value,
                conversation_id,
            )

            return fsm

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(
                "FSM load: failed to parse stored state, creating new | "
                "conversation_id=%s | error=%s",
                conversation_id,
                str(e),
            )
            return cls(conversation_id)

    def _merge_entities(self, entities: dict[str, Any]) -> None:
        """
        Merge intent entities into collected data.

        Special handling for services list to accumulate rather than replace.
        """
        for key, value in entities.items():
            if key == "services" and isinstance(value, list):
                # Accumulate services, avoiding duplicates
                existing = self._collected_data.get("services", [])
                for service in value:
                    if service not in existing:
                        existing.append(service)
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
