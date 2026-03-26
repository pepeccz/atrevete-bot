"""
BookingContext — Slim data-bag for the LLM-driven booking flow.

Replaces the rigid BookingDraftContext + BookingSubstep enum from v6.
Every field maps 1:1 to either a BookSchema requirement or a prompt
rendering need. There is NO step enum, NO transition table.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar


CLEARABLE_NONE_FIELDS: frozenset[str] = frozenset({"offered_slots", "selected_slot"})
"""Fields that must be serialized even when their value is None.

merge_dicts performs a shallow merge ({**current, **update}). If a key is ABSENT from
the update dict, the stale value in current survives. These two fields must be explicitly
set to None (rather than omitted) so that merge_dicts can overwrite stale values after
SLOT_TAKEN clears them.
"""


class InterpretationReason(StrEnum):
    """Canonical semantic reasons produced while interpreting availability results.

    The values are shared by booking mode and availability tools so semantic
    payloads stay stable across prompt rendering, transition decisions, and tests.
    """

    MINIMUM_DAYS_RULE = "minimum_days_rule"
    NO_AVAILABILITY = "no_availability"
    STYLIST_UNAVAILABLE = "stylist_unavailable"
    SUCCESS = "success"


@dataclass
class BookingContext:
    """Collected booking data for the LLM-driven booking flow.

    Fields are organized in logical groups matching the booking workflow.
    All fields are optional — the LLM decides what to collect next.
    """

    # ── Primary service (populated by extract_service_fields) ───────────
    service_id: str | None = None
    service_name: str | None = None
    service_category: str | None = None
    service_duration_minutes: int | None = None
    service_family: str | None = None

    # ── Services list (primary + add-ons, passed to book().services) ────
    selected_services: list[str] = field(default_factory=list)
    selected_services_details: list[dict[str, Any]] = field(default_factory=list)

    # ── Stylist (populated by extract_stylist_fields or pre-resolver) ───
    stylist_id: str | None = None
    stylist_name: str | None = None

    # ── Slot (populated after user confirms) ────────────────────────────
    selected_slot: dict[str, Any] | None = None

    # ── Offered slots (ephemeral, for prompt rendering) ─────────────────
    offered_slots: list[dict[str, Any]] | None = None

    # ── Customer (populated by extract_customer_fields or state) ────────
    customer_name: str | None = None
    customer_id: str | None = None

    # ── Optional data ───────────────────────────────────────────────────
    notes: str | None = None

    # ── Disambiguation state (from search_services shapes 2 & 3) ───────
    pending_clarifications: list[dict[str, Any]] = field(default_factory=list)
    candidate_services: list[dict[str, Any]] = field(default_factory=list)

    # ── Hints (from pre-resolvers) ──────────────────────────────────────
    service_audience_hint: str | None = None
    prefetched_stylists: list[dict[str, Any]] = field(default_factory=list)
    soonest_any_slot: str | None = None
    recurrent_stylist_hint: str | None = None

    # ── Combo recommendations (populated by extract_service_fields) ────
    pending_recommendations: list[str] = field(default_factory=list)
    recommendations_shown: bool = False
    recommendations_declined: bool = False

    # ── Failure tracking ────────────────────────────────────────────────
    book_failure_count: int = 0
    manage_customer_failure_count: int = 0
    needs_availability_refresh: bool = False

    # ── Service lock (prevents overwrite during SLOT_TAKEN retry) ──────
    services_locked: bool = False

    # ── Confirmation gate (prevents book() without user confirmation) ──
    confirmation_shown: bool = False
    confirmation_summary_sent: bool = False  # F-2: set by code when summary is rendered

    # ── Tool-skip reminders (injected when LLM skips tools) ──────────────
    force_search_services_reminder: bool = False
    force_list_stylists_reminder: bool = False
    force_stylist_correction: bool = False

    # ── Internal (not serialized) ───────────────────────────────────────
    _booking_completed: bool = field(default=False, repr=False)

    # ── Display maps (ClassVar — excluded from dataclass fields) ────────
    _AUDIENCE_DISPLAY: ClassVar[dict[str, str]] = {
        "adult_female": "dama",
        "adult_male": "caballero",
        "child_male": "niño",
        "child_female": "niña",
        "baby": "bebé",
    }

    # ═══════════════════════════════════════════════════════════════════
    # Methods
    # ═══════════════════════════════════════════════════════════════════

    def reset_transient(self) -> None:
        """Clear all transient booking fields after a successful booking.

        Call this immediately after setting _booking_completed = True so the
        context is clean for a potential follow-up booking in the same session.
        Fields that identify the customer (customer_name, customer_id) and
        stylist (stylist_id, stylist_name) are intentionally preserved as they
        are likely to be reused.
        """
        self.selected_services = []
        self.selected_services_details = []
        self.pending_clarifications = []
        self.candidate_services = []
        self.service_audience_hint = None
        self.notes = None
        self.prefetched_stylists = []
        self.soonest_any_slot = None
        self.recurrent_stylist_hint = None
        self.pending_recommendations = []
        self.recommendations_shown = False
        self.recommendations_declined = False
        self.book_failure_count = 0
        self.manage_customer_failure_count = 0
        self.needs_availability_refresh = False
        self.services_locked = False
        self.confirmation_shown = False
        self.confirmation_summary_sent = False
        self.force_search_services_reminder = False
        self.force_list_stylists_reminder = False
        self.force_stylist_correction = False

    def is_ready_to_book(self) -> bool:
        """Check if all REQUIRED fields for book() are present."""
        has_service = bool(self.service_id or self.selected_services)
        has_stylist = bool(self.stylist_id)
        has_slot = bool(self.selected_slot and self.selected_slot.get("start_time"))
        has_customer = bool(self.customer_name or self.customer_id)
        return has_service and has_stylist and has_slot and has_customer

    def collected_summary(self) -> str:
        """Render human-readable summary of collected data for prompt injection."""
        lines: list[str] = []
        # P4 fix: fallback to first selected_services entry when service_name is None
        display_service_name = self.service_name
        if not display_service_name and self.selected_services:
            display_service_name = self.selected_services[0]
        if display_service_name:
            parts = [display_service_name]
            if self.service_duration_minutes:
                parts.append(f"{self.service_duration_minutes} min")
            if self.service_category:
                parts.append(self.service_category)
            lines.append(f"✅ Servicio: {' — '.join(parts)}")
        if self.selected_services and len(self.selected_services) > 1:
            extras = [s for s in self.selected_services if s != display_service_name]
            if extras:
                lines.append(f"✅ Servicios adicionales: {', '.join(extras)}")
        if self.service_audience_hint:
            display = self._AUDIENCE_DISPLAY.get(
                self.service_audience_hint, self.service_audience_hint
            )
            lines.append(f"✅ Audiencia: {display}")
        if self.stylist_name:
            lines.append(f"✅ Estilista: {self.stylist_name}")
        if self.selected_slot:
            slot_date = self.selected_slot.get("date", "")
            slot_time = self.selected_slot.get("time", "")
            lines.append(f"✅ Horario: {slot_date} a las {slot_time}")
        if self.customer_name:
            lines.append(f"✅ Nombre: {self.customer_name}")
        if self.customer_id:
            lines.append(f"✅ Customer ID: {self.customer_id}")
        if self.service_id:
            lines.append(f"✅ Service ID: {self.service_id}")
        if self.notes:
            lines.append(f"✅ Notas: {self.notes}")
        return "\n".join(lines) if lines else "(ningún dato recogido todavía)"

    def missing_summary(self) -> str:
        """Render human-readable summary of missing REQUIRED fields.

        Note: selected_slot is NOT checked here because slot selection is managed
        conversationally by the LLM (it calls book() with slot data directly).
        offered_slots presence is used as a proxy for "date/time in progress".
        """
        missing: list[str] = []
        if not self.service_name and not self.selected_services:
            missing.append("servicio")
        if not self.stylist_id:
            missing.append("estilista")
        if not self.offered_slots:
            missing.append("fecha/hora")
        if not self.customer_name:
            if self.manage_customer_failure_count >= 2:
                missing.append("nombre (⚠️ guardar falló — pedir confirmación verbal)")
            else:
                missing.append("nombre")
        # Show customer_id as missing only when we have a name but no ID.
        # This guides the LLM to call manage_customer before book().
        if self.customer_name and not self.customer_id:
            missing.append("customer_id (llamá manage_customer para obtenerlo)")
        if not missing:
            return "✅ Todos los datos requeridos están completos"
        return "\n".join(f"❌ {label.capitalize()}: pendiente" for label in missing)

    def to_mode_context(self) -> dict[str, Any]:
        """Serialize to dict for mode_context storage.

        Fields in CLEARABLE_NONE_FIELDS are always included even when None, so that
        merge_dicts can overwrite stale values already present in LangGraph state.
        All other None/empty values are omitted to keep mode_context lean.
        """
        raw = dataclasses.asdict(self)
        return {
            k: v
            for k, v in raw.items()
            if not k.startswith("_")
            and (k in CLEARABLE_NONE_FIELDS or (v is not None and v != [] and v != {}))
        }

    @classmethod
    def from_mode_context(cls, mode_context: dict[str, Any]) -> BookingContext:
        """Hydrate from mode_context dict (tolerant of missing/extra keys)."""
        field_names = {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}
        filtered = {k: v for k, v in mode_context.items() if k in field_names}
        return cls(**filtered)


def preserve_booking_context(
    context: dict[str, Any] | None,
    target_mode: str,
) -> dict[str, Any]:
    """Snapshot booking context for draft storage during mode transition.

    mode_context is already a clean dict (no stale FSM fields), so a simple
    shallow copy is sufficient — no field-filtering needed.
    """
    if not context:
        return {}
    snapshot = dict(context)
    if target_mode.upper() == "ESCALATION":
        snapshot["awaiting_human"] = True
    return snapshot
