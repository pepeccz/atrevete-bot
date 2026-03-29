"""
AppointmentContext — Slim data-bag for the LLM-driven appointment management flow.

Mirrors the exact same architecture as BookingContext in booking_context.py.
There is NO step enum, NO transition table, NO FSM sub-steps.

Every field maps 1:1 to either a flow requirement or a prompt rendering need:
- ``action``: which sub-flow the LLM is driving (query / cancel / reschedule)
- ``appointments_list``: loaded from DB, displayed as a numbered list to the user
- ``selected_appointment_id``: set by the pre-resolver after the user picks a number
- ``selected_appointment_snapshot``: frozen copy of the appointment dict at selection time
- ``offered_slots``: availability results shown for reschedule flow
- ``pending_new_slot``: the slot the user wants to reschedule to (before confirmation)
- ``pending_confirmation`` / ``pending_confirmation_type``: Python-enforced safety gates
- ``action_completed``: set after a cancel or reschedule executes successfully
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppointmentContext:
    """Collected appointment management data for the LLM-driven flow.

    Fields are organized by flow. All fields are optional — the LLM
    decides what to ask/call next based on collected/missing data.
    There is NO step enum, NO transition table.

    Usage pattern (identical to BookingContext):
        ctx = AppointmentContext.from_mode_context(state["mode_context"])
        # ... pre-resolvers mutate ctx ...
        return {"mode_context": ctx.to_mode_context()}
    """

    # ── Action (detected by pre-resolver from intent) ────────────────────
    action: str = ""
    """Sub-flow: "query" | "cancel" | "reschedule" | "" (not yet determined)."""

    # ── Appointments list (loaded from DB by list_customer_appointments) ──
    appointments_list: list[dict[str, Any]] = field(default_factory=list)
    """
    Each dict: {
        id: str (UUID),
        date_display: str (e.g. "viernes 20 de diciembre"),
        time_display: str (e.g. "10:00"),
        service_name: str,
        stylist_name: str,
        status: str,
        start_time_iso: str (ISO 8601, for eligibility checks),
    }
    """

    # ── Selected appointment ──────────────────────────────────────────────
    selected_appointment_id: str = ""
    """UUID string of the appointment the user chose from the list."""

    selected_appointment_snapshot: dict[str, Any] = field(default_factory=dict)
    """Frozen copy of the chosen appointment dict (from appointments_list)."""

    # ── Reschedule-specific ───────────────────────────────────────────────
    offered_slots: list[dict[str, Any]] = field(default_factory=list)
    """Available slots returned by check_availability / find_next_available."""

    pending_new_slot: dict[str, Any] = field(default_factory=dict)
    """The slot the user wants to move to, pending confirmation."""

    # ── Confirmation gates (Python-enforced safety) ───────────────────────
    pending_confirmation: bool = False
    """
    MUST be True before cancel_appointment or reschedule_appointment executes.
    Set to True by the pre-resolver after the user explicitly says "sí".
    _pre_tool_call() blocks both destructive tools while this is False.
    """

    pending_confirmation_type: str = ""
    """
    Which action is pending confirmation: "cancel" | "reschedule" | "".
    Used by _pre_tool_call() to match gate to tool.
    """

    # ── Completion flag ───────────────────────────────────────────────────
    action_completed: bool = False
    """True after a cancel or reschedule has been executed successfully."""

    # ═══════════════════════════════════════════════════════════════════════
    # Serialization / deserialization
    # ═══════════════════════════════════════════════════════════════════════

    def to_mode_context(self) -> dict[str, Any]:
        """Serialize to dict for mode_context storage.

        Follows the same omission rules as BookingContext.to_mode_context():
        - Fields starting with ``_`` are excluded (internal/ClassVar).
        - None values, empty lists, empty dicts, empty strings, and False booleans
          are omitted to keep mode_context lean and avoid merge_dicts conflicts.

        Exception: ``pending_confirmation`` is always included when True so that
        the merge_dicts reducer cannot accidentally overwrite it with a stale False.
        """
        raw = dataclasses.asdict(self)
        result: dict[str, Any] = {}
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            # Always include pending_confirmation when True (safety gate must persist)
            if k == "pending_confirmation" and v is True:
                result[k] = v
                continue
            # Omit empty/falsy values to keep mode_context lean
            if v is None or v == [] or v == {} or v == "" or v is False:
                continue
            result[k] = v
        return result

    @classmethod
    def from_mode_context(cls, ctx: dict[str, Any]) -> AppointmentContext:
        """Hydrate from mode_context dict (tolerant of missing/extra keys).

        Follows the exact same pattern as BookingContext.from_mode_context():
        - Unknown keys are silently ignored (future-proof).
        - Missing keys fall back to dataclass defaults.
        """
        field_names = {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}
        filtered = {k: v for k, v in ctx.items() if k in field_names}
        return cls(**filtered)

    # ═══════════════════════════════════════════════════════════════════════
    # Prompt rendering helpers
    # ═══════════════════════════════════════════════════════════════════════

    def collected_summary(self) -> str:
        """Render human-readable summary of collected data for prompt injection.

        The LLM receives this as the ``<collected_data>`` section so it can
        decide what to ask/call next without re-reading the full history.
        """
        lines: list[str] = []

        if self.action:
            action_display = {
                "query": "ver citas",
                "cancel": "cancelar cita",
                "reschedule": "reagendar cita",
            }.get(self.action, self.action)
            lines.append(f"✅ Acción: {action_display}")

        if self.appointments_list:
            lines.append(f"✅ Citas cargadas: {len(self.appointments_list)} cita(s)")

        if self.selected_appointment_id:
            snapshot = self.selected_appointment_snapshot
            if snapshot:
                date_display = snapshot.get("date_display", "")
                time_display = snapshot.get("time_display", "")
                stylist = snapshot.get("stylist_name", "")
                service = snapshot.get("service_name", "")
                lines.append(
                    f"✅ Cita seleccionada: {date_display} a las {time_display} "
                    f"con {stylist} ({service})"
                )
            else:
                lines.append(f"✅ Cita seleccionada: ID {self.selected_appointment_id}")

        if self.offered_slots:
            lines.append(f"✅ Horarios ofrecidos: {len(self.offered_slots)} opción(es)")

        if self.pending_new_slot:
            slot_time = self.pending_new_slot.get("time", "")
            slot_date = self.pending_new_slot.get("date", "")
            lines.append(f"✅ Nuevo horario seleccionado: {slot_date} a las {slot_time}")

        if self.pending_confirmation:
            lines.append(
                f"✅ Confirmación recibida: pendiente de ejecutar {self.pending_confirmation_type}"
            )

        if self.action_completed:
            lines.append("✅ Acción completada exitosamente")

        return "\n".join(lines) if lines else "(ningún dato recogido todavía)"

    def missing_summary(self) -> str:
        """Render human-readable summary of missing data for prompt injection.

        The LLM receives this as the ``<missing_data>`` section so it knows
        what to collect or ask next.
        """
        missing: list[str] = []

        if not self.action:
            missing.append("acción (¿consultar, cancelar o reagendar?)")
            return "\n".join(f"❌ {m.capitalize()}: pendiente" for m in missing)

        if not self.appointments_list and not self.action_completed:
            missing.append("lista de citas (llamá list_customer_appointments)")

        if (
            self.appointments_list
            and not self.selected_appointment_id
            and not self.action_completed
        ):
            missing.append(
                "selección de cita (mostrá la lista numerada y esperá que el cliente elija)"
            )

        if self.action in ("cancel", "reschedule") and self.selected_appointment_id:
            if self.action == "reschedule" and not self.pending_new_slot:
                if not self.offered_slots:
                    missing.append(
                        "horarios disponibles (llamá check_availability o find_next_available)"
                    )
                else:
                    missing.append("selección del nuevo horario")

            if not self.pending_confirmation and not self.action_completed:
                action_display = "cancelación" if self.action == "cancel" else "reagendado"
                missing.append(
                    f"confirmación del cliente para el {action_display} "
                    f"(mostrá el resumen y pedí confirmación explícita)"
                )

        if not missing:
            return "✅ Todos los datos necesarios están completos"

        return "\n".join(f"❌ {m.capitalize()}: pendiente" for m in missing)

    # ═══════════════════════════════════════════════════════════════════════
    # State management helpers
    # ═══════════════════════════════════════════════════════════════════════

    def reset_transient(self) -> None:
        """Clear transient fields after an action completes.

        Call this immediately after setting ``action_completed = True`` so the
        context is ready for a potential follow-up action in the same session.
        ``action`` is preserved so the LLM knows what was just completed.
        """
        self.appointments_list = []
        self.selected_appointment_id = ""
        self.selected_appointment_snapshot = {}
        self.offered_slots = []
        self.pending_new_slot = {}
        self.pending_confirmation = False
        self.pending_confirmation_type = ""
