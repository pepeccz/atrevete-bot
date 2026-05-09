"""Backwards-compatibility stub — DB-bound helpers promoted to BookingQueryService (PR#2).

Pure utility functions are re-exported here for any existing test or code that imports
from this module path. New code MUST import from:
  - agent.tools.booking_helpers (pure utils)
  - agent.services.booking_query_service (DB-bound resolvers)

This file will be deleted in a future cleanup pass once all import sites are updated.
"""

# Re-export pure utils for backwards compatibility
from agent.tools.booking_helpers import (  # noqa: F401
    _compute_first_valid_date,
    _normalize_name,
    _strip_diminutive,
    _validate_full_name,
)
