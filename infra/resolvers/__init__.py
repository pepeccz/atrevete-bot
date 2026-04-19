"""Resolver sub-package — deterministic pre-loop signal resolvers (P8, P3)."""

from infra.resolvers.affirmation import AFFIRMATION_PHRASES, is_affirmation, normalize_for_affirmation
from infra.resolvers.negation import NEGATION_PHRASES, is_negation, normalize_for_negation

__all__ = [
    "is_negation",
    "normalize_for_negation",
    "NEGATION_PHRASES",
    "is_affirmation",
    "normalize_for_affirmation",
    "AFFIRMATION_PHRASES",
]

# ---------------------------------------------------------------------------
# Registry wiring — register affirmation resolver in agent/core/resolvers.py
# Design ref: §10 (T1.6 acceptance)
# Wrapped in try/except to survive _clear_for_tests() + re-import in tests.
# ---------------------------------------------------------------------------


def _resolver_fn(user_text: str, state: object) -> dict | None:
    """Thin wrapper adapting is_affirmation to the Resolver protocol.

    Returns a state patch dict if affirmation detected while _confirmation_shown
    is active; None otherwise (resolver not applicable).
    """
    bc = {}
    if isinstance(state, dict):
        bc = state.get("booking_context") or {}

    # Only fire when confirmation has been shown and not yet confirmed (R20)
    if not (bc.get("_confirmation_shown") and not bc.get("confirmed")):
        return None

    matched, phrase, distance = is_affirmation(user_text)
    if not matched:
        return None

    return {
        "booking_context": {**bc, "confirmed": True},
        "_telemetry": {"matched_phrase": phrase or "", "fuzzy_distance": float(distance)},
    }


try:
    from agent.core.resolvers import register as _register

    _register("affirmation", _resolver_fn)
except ValueError:
    # Already registered (e.g. module re-imported in same process)
    pass
