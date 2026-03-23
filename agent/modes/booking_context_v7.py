"""
BookingContextV7 — Slim data-bag for the LLM-driven booking flow.

Replaces the rigid BookingDraftContext + BookingSubstep enum from v6.
Every field maps 1:1 to either a BookSchema requirement or a prompt
rendering need. There is NO step enum, NO transition table.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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
class BookingContextV7:
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
    pending_clarification: dict[str, Any] | None = None
    candidate_services: list[dict[str, Any]] = field(default_factory=list)

    # ── Hints (from pre-resolvers) ──────────────────────────────────────
    service_audience_hint: str | None = None
    prefetched_stylists: list[dict[str, Any]] = field(default_factory=list)
    soonest_any_slot: str | None = None
    recurrent_stylist_hint: str | None = None

    # ── Book failure tracking ────────────────────────────────────────────
    book_failure_count: int = 0

    # ── Internal (not serialized) ───────────────────────────────────────
    _booking_completed: bool = field(default=False, repr=False)

    # ═══════════════════════════════════════════════════════════════════
    # Methods
    # ═══════════════════════════════════════════════════════════════════

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
        if self.service_name:
            parts = [self.service_name]
            if self.service_duration_minutes:
                parts.append(f"{self.service_duration_minutes} min")
            if self.service_category:
                parts.append(self.service_category)
            lines.append(f"✅ Servicio: {' — '.join(parts)}")
        if self.selected_services and len(self.selected_services) > 1:
            extras = [s for s in self.selected_services if s != self.service_name]
            if extras:
                lines.append(f"✅ Servicios adicionales: {', '.join(extras)}")
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
            missing.append("nombre")
        if not missing:
            return "✅ Todos los datos requeridos están completos"
        return "\n".join(f"❌ {label.capitalize()}: pendiente" for label in missing)

    def to_mode_context(self) -> dict[str, Any]:
        """Serialize to dict for mode_context storage."""
        raw = dataclasses.asdict(self)
        return {
            k: v
            for k, v in raw.items()
            if not k.startswith("_") and v is not None and v != [] and v != {}
        }

    @classmethod
    def from_mode_context(cls, mode_context: dict[str, Any]) -> BookingContextV7:
        """Hydrate from mode_context dict (tolerant of missing/extra keys)."""
        field_names = {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}
        filtered = {k: v for k, v in mode_context.items() if k in field_names}
        return cls(**filtered)


def preserve_booking_context_v7(
    context: dict[str, Any] | None,
    target_mode: str,
) -> dict[str, Any]:
    """Snapshot v7 booking context for draft storage during mode transition.

    v7 mode_context is already a clean dict (no stale FSM fields), so a simple
    shallow copy is sufficient — no field-filtering needed.
    """
    if not context:
        return {}
    snapshot = dict(context)
    if target_mode.upper() == "ESCALATION":
        snapshot["awaiting_human"] = True
    return snapshot
