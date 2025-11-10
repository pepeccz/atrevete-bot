"""
Atomic Transaction Handlers for v3.0 architecture.

Transaction handlers encapsulate complex multi-step operations that must execute
atomically (all succeed or all rollback). They coordinate between:
- PostgreSQL database (via SQLAlchemy async sessions)
- Google Calendar API (event creation/updates)

Key design principles:
1. SERIALIZABLE isolation level for DB transactions
2. SELECT FOR UPDATE row locks to prevent race conditions
3. Complete rollback on any step failure (including external APIs)
4. Exhaustive logging with trace_id for debugging
5. Descriptive error codes for tool results

Transaction handlers:
- BookingTransaction: Create provisional/confirmed appointments
- ModificationTransaction: Modify existing appointments (future)
- CancellationTransaction: Cancel appointments with refunds (future)
"""

from agent.transactions.booking_transaction import BookingTransaction

__all__ = ["BookingTransaction"]
