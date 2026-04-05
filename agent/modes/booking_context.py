"""
BookingContext — Minimal data-bag for the LLM-driven booking flow.

20 fields only — every field maps 1:1 to either a BookSchema requirement
or a prompt rendering need. No hint fields, no counters, no force-flags.
The LLM reads conversation history and handles extraction itself.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class InterpretationReason(StrEnum):
    """Canonical semantic reasons produced while interpreting availability results.

    The values are shared by booking mode and availability tools so semantic
    payloads stay stable across prompt rendering, transition decisions, and tests.
    Kept for backward compat — availability_tools.py imports this enum.
    """

    MINIMUM_DAYS_RULE = "minimum_days_rule"
    NO_AVAILABILITY = "no_availability"
    STYLIST_UNAVAILABLE = "stylist_unavailable"
    SUCCESS = "success"


CLEARABLE_NONE_FIELDS: frozenset[str] = frozenset({"offered_slots", "selected_slot"})
"""Fields that must be serialized even when their value is None.

merge_dicts performs a shallow merge ({**current, **update}). If a key is ABSENT from
the update dict, the stale value in current survives. These two fields must be explicitly
set to None (rather than omitted) so that merge_dicts can overwrite stale values after
SLOT_TAKEN clears them.
"""


@dataclass
class BookingContext:
    """Minimal booking state — only what cannot be derived from tool results or conversation."""

    # ── Service ──────────────────────────────────────────────────────────────
    service_id: str | None = None
    service_name: str | None = None
    service_duration_minutes: int | None = None
    service_category: str | None = None
    selected_services: list[str] = field(default_factory=list)
    selected_services_details: list[dict] = field(default_factory=list)
    pending_clarifications: list[dict] = field(default_factory=list)
    candidate_services: list[dict] = field(default_factory=list)

    # ── Stylist & availability ────────────────────────────────────────────────
    stylist_id: str | None = None
    stylist_name: str | None = None
    prefetched_stylists: list[dict] = field(default_factory=list)
    offered_slots: list[dict] | None = None
    selected_slot: dict | None = None
    hold_id: str | None = None

    # ── Customer ──────────────────────────────────────────────────────────────
    customer_id: str | None = None
    customer_name: str | None = None
    notes: str | None = None

    # ── Disambiguation memory ──────────────────────────────────────────────
    resolved_axes: dict[str, str] = field(default_factory=dict)

    # ── Booking hints (extracted from first user message) ────────────────────
    preferred_stylist_name: str | None = None
    preferred_date_hint: str | None = None

    # ── Confirmation ─────────────────────────────────────────────────────────
    confirmation_shown: bool = False
    confirmation_summary_sent: bool = False

    # ── Internal (not serialized) ─────────────────────────────────────────────
    _booking_completed: bool = field(default=False, repr=False)

    # ═══════════════════════════════════════════════════════════════════
    # Methods
    # ═══════════════════════════════════════════════════════════════════

    @classmethod
    def from_mode_context(cls, data: dict[str, Any]) -> BookingContext:
        """Tolerant hydration — silently ignores ALL unknown keys.

        Critical for backward compat with existing Redis checkpoints that
        have 49 fields from the previous BookingContext implementation.
        Missing keys fall back to dataclass defaults.
        """
        field_names = {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}
        known = {k: v for k, v in data.items() if k in field_names}
        unknown_keys = set(data.keys()) - field_names
        if unknown_keys:
            logger.debug(
                "from_mode_context: silently dropping %d unknown key(s): %s",
                len(unknown_keys),
                sorted(unknown_keys),
            )
        return cls(**known)

    def to_mode_context(self) -> dict[str, Any]:
        """Serialize all fields to dict. Skip None values and empty lists/dicts.

        Fields in CLEARABLE_NONE_FIELDS are always included even when None so
        that merge_dicts can overwrite stale values already present in LangGraph state.
        Boolean False and int 0 ARE serialized (they're meaningful state).
        """
        raw = dataclasses.asdict(self)
        return {
            k: v
            for k, v in raw.items()
            if not k.startswith("_")
            and (k in CLEARABLE_NONE_FIELDS or (v is not None and v != [] and v != {}))
        }

    def missing_summary(self) -> str:
        """Returns <missing_data> XML block listing what's still needed.

        Logic:
        - service missing → "Servicio: pendiente"
        - stylist missing → "Estilista: pendiente"
        - slots missing AND stylist set → "Horario: pendiente"
        - customer_name missing → "Nombre: pendiente"
        - notes missing AND service/stylist/slot/name all set → "Notas: pendiente"
        - If nothing missing → return empty string
        """
        missing: list[str] = []

        if not self.service_name and not self.selected_services:
            missing.append("❌ Servicio: pendiente")

        if not self.stylist_id and (self.service_name or self.selected_services):
            missing.append("❌ Estilista: pendiente")

        if self.selected_slot is not None:
            pass  # slot resolved — don't add to missing
        elif self.offered_slots:
            missing.append("⏳ Horario: elige uno de los ofrecidos")
        else:
            missing.append("❌ Fecha/hora: pendiente")

        service_known = bool(self.service_name or self.selected_services)
        if (
            not self.customer_name
            and service_known
            and self.stylist_id
            and self.selected_slot is not None
        ):
            missing.append("❌ Nombre: pendiente")

        if self.customer_name and not self.customer_id:
            missing.append("❌ Customer ID: llamá manage_customer")

        # Notes step: only show when all other required fields are complete
        everything_else_complete = not missing
        if everything_else_complete and not self.notes:
            missing.append("❌ Notas: preguntá si tiene preferencias")

        return "\n".join(missing)

    def collected_summary(self) -> str:
        """Returns <collected_data> XML block with what's confirmed.

        Only includes non-None fields. Used for prompt injection.
        """
        lines: list[str] = []

        # Service — fallback to first selected_services entry when service_name is None
        display_service_name = self.service_name
        if not display_service_name and self.selected_services:
            display_service_name = self.selected_services[0]

        if display_service_name:
            # Show all services as a combined line when multiple
            if self.selected_services and len(self.selected_services) > 1:
                all_names = " + ".join(self.selected_services)
                parts = [all_names]
            else:
                parts = [display_service_name]
            if self.service_duration_minutes:
                suffix = " total" if len(self.selected_services) > 1 else ""
                parts.append(f"{self.service_duration_minutes} min{suffix}")
            if self.service_category:
                parts.append(self.service_category)
            lines.append(f"✅ Servicio: {' — '.join(parts)}")

        if self.stylist_name:
            lines.append(f"✅ Estilista: {self.stylist_name}")

        if self.selected_slot:
            slot_date = self.selected_slot.get("date", "")
            slot_time = self.selected_slot.get("time", "")
            lines.append(f"✅ Horario: {slot_date} a las {slot_time}")

        if self.customer_name:
            lines.append(f"✅ Nombre: {self.customer_name}")

        if self.resolved_axes:
            axis_labels = {
                "audience": "Público",
                "hair_length": "Pelo",
                "hair_density": "Densidad",
            }
            value_labels = {
                "adult_female": "Mujer",
                "adult_male": "Hombre",
                "child_female": "Niña",
                "child_male": "Niño",
                "short_medium": "corto/medio",
                "long": "largo",
                "normal": "normal",
                "extra": "extra (muy largo/denso)",
            }
            for axis, value in self.resolved_axes.items():
                label = axis_labels.get(axis, axis)
                val_label = value_labels.get(value, value)
                lines.append(f"✅ {label}: {val_label}")

        if self.preferred_stylist_name and not self.stylist_id:
            lines.append(f"💡 Estilista preferida (sin confirmar): {self.preferred_stylist_name}")
        if self.preferred_date_hint and not self.selected_slot:
            lines.append(f"💡 Fecha preferida (sin confirmar): {self.preferred_date_hint}")

        if self.customer_id:
            lines.append(f"✅ Customer ID: {self.customer_id}")

        if self.service_id:
            lines.append(f"✅ Service ID: {self.service_id}")

        if self.notes:
            lines.append(f"✅ Notas: {self.notes}")

        return "\n".join(lines) if lines else "(ningún dato recogido todavía)"

    def reset_transient(self) -> None:
        """Reset ephemeral booking fields after a successful booking or flow restart.

        Keeps: service/stylist/customer/notes data (likely to be reused).
        Resets: offered_slots, selected_slot, hold_id, confirmation flags.
        """
        self.offered_slots = []
        self.selected_slot = None
        self.hold_id = None
        self.confirmation_shown = False
        self.confirmation_summary_sent = False


def format_service_list(services: list[str]) -> str:
    """Format service names as a human-readable Spanish list.

    Examples:
        [] → ""
        ["Corte Caballero"] → "Corte Caballero"
        ["Corte Caballero", "Corte Niño"] → "Corte Caballero y Corte Niño"
        ["A", "B", "C"] → "A, B y C"
    """
    if not services:
        return ""
    if len(services) == 1:
        return services[0]
    return f"{', '.join(services[:-1])} y {services[-1]}"


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
