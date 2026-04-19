"""
Transaction Validators — pre-commit business rule checks.

Validators for business rules and constraints that must be checked before
executing atomic transactions (e.g., BookingTransaction).

HISTORICAL CONTEXT: previously lived under agent/validators/. Moved under
agent/transactions/ during the agent/ folder consolidation because every
validator here is coupled to the booking transaction lifecycle.

Validators:
- validate_category_consistency: Ensures all services in a booking are same category
- validate_slot_availability: Checks slot is free with 10-min buffer
- validate_3_day_rule: Ensures booking meets 3-day minimum notice requirement
"""

from agent.transactions.validators.transaction_validators import (
    validate_3_day_rule,
    validate_category_consistency,
    validate_slot_availability,
)

__all__ = [
    "validate_category_consistency",
    "validate_slot_availability",
    "validate_3_day_rule",
]
