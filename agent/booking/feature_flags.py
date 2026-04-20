"""
Feature flag helpers for the BookingCapability path.

Phase 7: USE_CAPABILITY_BOOKING flag removed — BookingGroundingMiddleware and
BookingInvariantMiddleware are now unconditionally active. This module is kept
as a thin shim for any code that still imports BOOKING_CAPABILITY_KEY_PREFIX.
"""

from __future__ import annotations

# Redis key prefix retained for backward compatibility (admin panel may reference it)
BOOKING_CAPABILITY_KEY_PREFIX = "booking:capability:"

# Deprecated alias
BOOKING_FLAG_KEY_PREFIX = BOOKING_CAPABILITY_KEY_PREFIX
