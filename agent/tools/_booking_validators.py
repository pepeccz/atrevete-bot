"""Shared booking-date validation layer.

Single source of truth for booking-date legality.
Consumers: update_booking._update_booking_impl, manage_appointments._reschedule_appointment.

Guards applied in order (G1 → G2 → G3, short-circuit on first failure):
  G1 — Resolve date: validate YYYY-MM-DD syntax or resolve relative text.
  G2 — Closed day: check against business hours table.
  G3 — Advance policy: enforce minimum lead-time (MIN_BOOKING_DAYS).

No I/O ownership beyond calling pure helpers + is_date_closed (DB-backed).
No dependency on ToolResponse or _booking_helpers.

Design: ADR-1 (module location), ADR-2 (error codes), ADR-3 (dataclass),
        ADR-4 (injectable ref_date), ADR-5 (async), ADR-6 (adapter mapping in callers),
        ADR-7 (short-circuit order).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Module-level imports so tests can patch them at the module level.
# These are the only two external dependencies of the validator.
from agent.booking.resolvers.time_resolver import MIN_BOOKING_DAYS, resolve_relative_date
from shared.business_hours_validator import is_date_closed

# ---------------------------------------------------------------------------
# Canonical error codes — exported, consumed by adapter mapping tables in callers
# ---------------------------------------------------------------------------

ERROR_INVALID_RELATIVE_DATE = "invalid_relative_date"
"""G1 failure: date text could not be resolved to a concrete day."""

ERROR_CLOSED_DAY = "closed_day"
"""G2 failure: resolved date falls on a closed day (Sunday / Monday / holiday)."""

ERROR_ADVANCE_POLICY_VIOLATED = "advance_policy_violated"
"""G3 failure: resolved date is sooner than today + MIN_BOOKING_DAYS."""

_MADRID_TZ = ZoneInfo("Europe/Madrid")


# ---------------------------------------------------------------------------
# Result dataclass (ADR-3: plain dataclass, not Pydantic)
# ---------------------------------------------------------------------------


@dataclass
class DateValidationResult:
    """Result of a booking-date validation pipeline run.

    On success: error_code=None, error_message=None, date_iso=YYYY-MM-DD resolved string.
    On failure: error_code is one of the ERROR_* constants, date_iso=None.
    payload carries extra context for callers (e.g. min_date, closed_date).
    """

    date_iso: str | None
    """Canonical YYYY-MM-DD string when resolved; None on G1 failure."""

    error_code: str | None
    """One of ERROR_INVALID_RELATIVE_DATE | ERROR_CLOSED_DAY | ERROR_ADVANCE_POLICY_VIOLATED | None."""

    error_message: str | None
    """Spanish, user-facing, ready to send. None on success."""

    payload: dict = field(default_factory=dict)
    """Extra context for callers: min_date, min_days, closed_date, reason, raw_text."""

    @property
    def ok(self) -> bool:
        """True when no error occurred and date_iso is resolved."""
        return self.error_code is None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def validate_booking_date(
    date_iso: str | None,
    date_text: str | None,
    *,
    ref_date: date | None = None,
    min_days: int | None = None,
) -> DateValidationResult:
    """Validate a booking date through G1 → G2 → G3 pipeline.

    Short-circuits on first failure: one actionable error per call.

    Args:
        date_iso:   Desired date as YYYY-MM-DD string. Takes priority over date_text.
        date_text:  Raw relative phrase from the user (e.g. "mañana", "el viernes").
                    Used only when date_iso is None or not a valid YYYY-MM-DD.
        ref_date:   Reference date for G3 comparison and relative resolution.
                    Defaults to today in Europe/Madrid when not provided.
                    Pass explicitly for deterministic tests (ADR-4).
        min_days:   Override for minimum lead-time days (B6: settings drift fix).
                    When None, falls back to the module-level MIN_BOOKING_DAYS constant.

    Returns:
        DateValidationResult — .ok=True on success, .error_code set on failure.
    """
    # Effective reference date (ADR-4)
    ref: date = ref_date if ref_date is not None else datetime.now(_MADRID_TZ).date()

    # ── G1: Resolve to a concrete YYYY-MM-DD ─────────────────────────────────
    resolved: date | None = None

    if date_iso is not None and _is_valid_iso_date(date_iso):
        # Syntactically valid ISO date provided directly
        resolved = date.fromisoformat(date_iso)
    elif date_text:
        # Attempt relative-date resolution
        resolved = resolve_relative_date(date_text, ref)

    if resolved is None:
        # G1 failure: could not resolve to a concrete date
        return DateValidationResult(
            date_iso=None,
            error_code=ERROR_INVALID_RELATIVE_DATE,
            error_message=(
                "No pude entender la fecha. "
                "¿Puedes decirme el día y mes (por ejemplo, 15 de mayo)?"
            ),
            payload={"raw_text": date_text},
        )

    # ── G2: Closed day ────────────────────────────────────────────────────────
    if await is_date_closed(resolved):
        weekday_name = _weekday_name_es(resolved)
        return DateValidationResult(
            date_iso=None,
            error_code=ERROR_CLOSED_DAY,
            error_message=(
                f"El salón está cerrado el {resolved.isoformat()} ({weekday_name}). "
                "Por favor, elige otro día."
            ),
            payload={
                "closed_date": resolved.isoformat(),
                "reason": weekday_name,
            },
        )

    # ── G3: Advance policy (lead-time) ────────────────────────────────────────
    effective_min_days: int = min_days if min_days is not None else MIN_BOOKING_DAYS
    min_date: date = ref + timedelta(days=effective_min_days)
    if resolved < min_date:
        return DateValidationResult(
            date_iso=None,
            error_code=ERROR_ADVANCE_POLICY_VIOLATED,
            error_message=(
                f"La fecha {resolved.isoformat()} viola la política de antelación mínima "
                f"({effective_min_days} días). "
                f"La primera fecha válida es el {min_date.isoformat()}."
            ),
            payload={
                "min_date": min_date.isoformat(),
                "min_days": effective_min_days,
            },
        )

    # ── Success ───────────────────────────────────────────────────────────────
    return DateValidationResult(
        date_iso=resolved.isoformat(),
        error_code=None,
        error_message=None,
        payload={},
    )


# ---------------------------------------------------------------------------
# Booking FK existence guards (I1)
# ---------------------------------------------------------------------------

ERROR_INVALID_SERVICE_IDS = "invalid_service_ids"
"""Returned when one or more service_id values are not found in the services table."""

ERROR_INVALID_STYLIST_ID = "invalid_stylist_id"
"""Returned when the stylist_id value is not found in the stylists table."""


@dataclass
class FKValidationResult:
    """Result of a FK existence check.

    On success: ok=True, error_code=None, error_message=None, missing_ids=[].
    On failure: ok=False, error_code set, error_message is a Spanish instruction
                for the LLM so it can self-correct by re-reading <catalog>.
    """

    ok: bool
    error_code: str | None
    error_message: str | None
    missing_ids: list = field(default_factory=list)


async def validate_service_ids_exist(session, service_ids: list) -> FKValidationResult:
    """Check that every UUID in service_ids exists in the services table.

    Executes a single SELECT id FROM services WHERE id = ANY(:ids).
    Returns a FKValidationResult with missing_ids populated on failure.

    Args:
        session:     An open async SQLAlchemy session (injected from the caller's block).
        service_ids: List of UUID objects to validate. Empty list returns ok=True.

    Returns:
        FKValidationResult with ok=True when all IDs exist; ok=False when any are missing.
    """
    from uuid import UUID as _UUID

    if not service_ids:
        return FKValidationResult(ok=True, error_code=None, error_message=None)

    from sqlalchemy import text as _text

    id_strings = [str(sid) for sid in service_ids]
    result = await session.execute(
        _text("SELECT id FROM services WHERE id = ANY(:ids)"),
        {"ids": id_strings},
    )
    found_ids = {row[0] for row in result.fetchall()}

    # Normalize to UUID objects for comparison
    found_uuids = set()
    for fid in found_ids:
        try:
            found_uuids.add(_UUID(str(fid)))
        except (ValueError, AttributeError):
            pass

    input_uuids = []
    for sid in service_ids:
        try:
            input_uuids.append(_UUID(str(sid)))
        except (ValueError, AttributeError):
            pass

    missing = [uid for uid in input_uuids if uid not in found_uuids]

    if not missing:
        return FKValidationResult(ok=True, error_code=None, error_message=None)

    missing_str = ", ".join(str(m) for m in missing)
    return FKValidationResult(
        ok=False,
        error_code=ERROR_INVALID_SERVICE_IDS,
        error_message=(
            f"service_id inválido: {missing_str}. "
            "Vuelve a leer el <catalog> y usa solo UUIDs que aparezcan tras id=."
        ),
        missing_ids=missing,
    )


async def validate_stylist_id_exists(session, stylist_id) -> FKValidationResult:
    """Check that stylist_id exists in the stylists table.

    Args:
        session:    An open async SQLAlchemy session.
        stylist_id: UUID object to validate.

    Returns:
        FKValidationResult with ok=True if found; ok=False if not.
    """
    from uuid import UUID as _UUID
    from sqlalchemy import text as _text

    result = await session.execute(
        _text("SELECT id FROM stylists WHERE id = :id"),
        {"id": str(stylist_id)},
    )
    row = result.fetchone()

    if row is not None:
        return FKValidationResult(ok=True, error_code=None, error_message=None)

    return FKValidationResult(
        ok=False,
        error_code=ERROR_INVALID_STYLIST_ID,
        error_message=(
            f"stylist_id inválido: {stylist_id}. "
            "Vuelve a leer el <catalog> y usa solo UUIDs de estilistas que aparezcan en el catálogo."
        ),
        missing_ids=[stylist_id],
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_DAY_NAMES_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _weekday_name_es(d: date) -> str:
    """Return the Spanish weekday name for a date."""
    return _DAY_NAMES_ES[d.weekday()]


def _is_valid_iso_date(value: str) -> bool:
    """Return True if value is a syntactically valid YYYY-MM-DD date string."""
    try:
        date.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False
