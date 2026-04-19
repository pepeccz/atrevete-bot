"""
Booking grounding module — pure deterministic next-action selection.

compute_next_prompt(state) evaluates BookingContext and returns a GroundingDirective
that tells the LLM exactly what to do next. No I/O, no side effects.

Design refs: design §4, §6 Q4, §6 Q8
Requirements: R1–R8
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constants — action values
# ---------------------------------------------------------------------------

ActionType = Literal[
    "ASK_SERVICE",
    "ASK_AUDIENCE",
    "ASK_MORE_SERVICES",
    "ASK_STYLIST",
    "ASK_AVAILABILITY",
    "ASK_SLOT",
    "ASK_NAME",
    "ASK_NOTES",
    "SHOW_CONFIRMATION",
    "AWAIT_CONFIRMATION",
    "CALL_BOOK",
    "BOOKING_COMPLETE",
    "ERROR_RECOVERY",
]


# ---------------------------------------------------------------------------
# GroundingDirective — frozen dataclass (immutable value object)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroundingDirective:
    """Result of compute_next_prompt. Carries the action + Spanish imperative directive.

    Fields:
        action: symbolic identifier for the required next action.
        directive: Spanish imperative string injected verbatim into [grounding].
        mandatory_next_call: tool name the LLM MUST call next, or None.
        context: data dict for LLM narration (e.g. stylist list, slot list, summary).
    """

    action: str
    directive: str
    mandatory_next_call: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _bc(state: dict[str, Any]) -> dict[str, Any]:
    """Extract booking_context from state, returning empty dict if absent."""
    ctx = state.get("booking_context") or {}
    return ctx if isinstance(ctx, dict) else {}


def _has_stylist(bc: dict[str, Any]) -> bool:
    """True when a stylist has been selected (named or no-preference)."""
    return bool(bc.get("last_stylist") or bc.get("no_preference_stylist"))


def _has_services(bc: dict[str, Any]) -> bool:
    """True when at least one service is recorded."""
    svcs = bc.get("last_services")
    return bool(svcs)


def _booking_complete(bc: dict[str, Any]) -> bool:
    """True when all required booking slots are filled."""
    return bool(
        _has_services(bc)
        and _has_stylist(bc)
        and bc.get("offered_slots")
        and bc.get("selected_slot")
        and bc.get("customer_name")
    )


# ---------------------------------------------------------------------------
# render_confirmation_summary — pure Python summary builder (R3, §6 Q8)
# ---------------------------------------------------------------------------


def render_confirmation_summary(bc: dict[str, Any]) -> str:
    """Render a deterministic Spanish confirmation summary from booking context.

    Output is injected verbatim into the [grounding] directive when action=SHOW_CONFIRMATION.
    The LLM copies it to the user without modification.

    Args:
        bc: BookingContext dict (must have services, stylist, selected_slot, customer_name).

    Returns:
        Formatted Spanish summary string.
    """
    services = ", ".join(bc.get("last_services") or []) or "—"
    stylist = bc.get("last_stylist") or "Sin preferencia"
    slot = bc.get("selected_slot") or {}
    date = slot.get("date") or "—"
    time = slot.get("time") or "—"
    name = bc.get("customer_name") or "—"
    notes = bc.get("notes") or None

    lines = [
        "📋 *Resumen de tu cita:*",
        f"• Servicio(s): {services}",
        f"• Estilista: {stylist}",
        f"• Fecha y hora: {date} a las {time}",
        f"• Nombre: {name}",
    ]
    if notes:
        lines.append(f"• Notas: {notes}")

    lines.append("")
    lines.append("¿Confirmamos? Respondé *sí* para reservar o *no* para cambiar algo.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# compute_next_prompt — 13-branch decision tree (R1, R2, R8)
# ---------------------------------------------------------------------------


def compute_next_prompt(state: dict[str, Any]) -> GroundingDirective:
    """Pure function: evaluate booking_context state and return the next required action.

    Branches evaluated in priority order (first match wins):
    1. _booking_completed          → BOOKING_COMPLETE
    2. confirmed == True           → CALL_BOOK
    3. _confirmation_shown & !confirmed → AWAIT_CONFIRMATION
    4. pending_disambiguations     → ASK_AUDIENCE
    5. no last_services            → ASK_SERVICE
    6. services & !add_more_asked  → ASK_MORE_SERVICES
    7. add_more_asked & !stylist   → ASK_STYLIST
    8. stylist & !offered_slots    → ASK_AVAILABILITY
    9. offered_slots & !selected_slot → ASK_SLOT
    10. selected_slot & !customer_name → ASK_NAME
    11. customer_name & notes_state == 'not_asked' → ASK_NOTES
    12. booking_complete & notes != 'not_asked' & !_confirmation_shown → SHOW_CONFIRMATION
    13. fallback                   → ERROR_RECOVERY

    Args:
        state: ConversationState dict (only booking_context is read).

    Returns:
        GroundingDirective (immutable).
    """
    bc = _bc(state)

    # ── Branch 1: already booked ────────────────────────────────────────────
    if bc.get("_booking_completed"):
        return GroundingDirective(
            action="BOOKING_COMPLETE",
            directive=(
                "La cita YA fue creada. "
                "NO llames book de nuevo. Despedite brevemente."
            ),
            mandatory_next_call=None,
            context={"booked_appointment_id": bc.get("booked_appointment_id")},
        )

    # ── Branch 2: confirmed → call book ─────────────────────────────────────
    if bc.get("confirmed") is True:
        return GroundingDirective(
            action="CALL_BOOK",
            directive="El cliente confirmó. LLAMA `book` AHORA, sin narración previa.",
            mandatory_next_call="book",
            context={},
        )

    # ── Branch 3: confirmation shown, awaiting answer ───────────────────────
    if bc.get("_confirmation_shown") and not bc.get("confirmed"):
        return GroundingDirective(
            action="AWAIT_CONFIRMATION",
            directive=(
                "Esperá la respuesta del cliente al resumen. "
                "No repitas el resumen. No llames tools."
            ),
            mandatory_next_call=None,
            context={},
        )

    # ── Branch 4: disambiguation pending ────────────────────────────────────
    pending = bc.get("pending_disambiguations") or []
    if pending:
        first = pending[0] if pending else {}
        return GroundingDirective(
            action="ASK_AUDIENCE",
            directive=(
                f"Servicio con variantes por audiencia: {first.get('family', '?')}. "
                "Preguntá: ¿es para señora, caballero, niño o bebé? "
                "NO llames update_booking todavía."
            ),
            mandatory_next_call=None,
            context={"pending": pending},
        )

    # ── Branch 5: no services ────────────────────────────────────────────────
    if not _has_services(bc):
        return GroundingDirective(
            action="ASK_SERVICE",
            directive=(
                "Preguntá qué servicio necesita. "
                "Si ya lo dijo, LLAMA update_booking con services=[...]."
            ),
            mandatory_next_call=None,
            context={},
        )

    # ── Branch 6: services set, add_more not asked ───────────────────────────
    if not bc.get("add_more_asked"):
        services_str = ", ".join(bc.get("last_services") or [])
        return GroundingDirective(
            action="ASK_MORE_SERVICES",
            directive=(
                f"Ya registraste: {services_str}. "
                "Preguntá '¿Algo más o con eso alcanza?'. No llames tools."
            ),
            mandatory_next_call=None,
            context={"services": bc.get("last_services") or []},
        )

    # ── Branch 7: add_more asked, no stylist ────────────────────────────────
    if not _has_stylist(bc):
        stylists = bc.get("available_stylists") or bc.get("_offered_stylists") or []
        return GroundingDirective(
            action="ASK_STYLIST",
            directive=(
                "Servicios cerrados. Mostrá la lista de estilistas y pedí elección "
                "(o 'sin preferencia'). "
                f"Estilistas: {stylists}"
            ),
            mandatory_next_call=None,
            context={"stylists": stylists},
        )

    # ── Branch 8: stylist set, no offered_slots ─────────────────────────────
    if not bc.get("offered_slots"):
        return GroundingDirective(
            action="ASK_AVAILABILITY",
            directive=(
                "Estilista y servicios listos. "
                "LLAMA check_availability AHORA."
            ),
            mandatory_next_call="check_availability",
            context={},
        )

    # ── Branch 9: slots offered, none selected ──────────────────────────────
    if not bc.get("selected_slot"):
        slots = bc.get("offered_slots") or []
        return GroundingDirective(
            action="ASK_SLOT",
            directive=(
                f"Presentá los {len(slots)} slots numerados y pedí que elija. "
                f"Slots: {slots}"
            ),
            mandatory_next_call=None,
            context={"slots": slots},
        )

    # ── Branch 10: slot selected, no customer name ───────────────────────────
    if not bc.get("customer_name"):
        return GroundingDirective(
            action="ASK_NAME",
            directive="Pedí el nombre completo del cliente.",
            mandatory_next_call=None,
            context={},
        )

    # ── Branch 11: name set, notes not asked ────────────────────────────────
    notes_state = bc.get("notes_state", "not_asked")
    if notes_state == "not_asked":
        return GroundingDirective(
            action="ASK_NOTES",
            directive=(
                "Preguntá si quiere añadir alguna nota (alergias, preferencias). "
                "Si el cliente dice que no, se marcará como skipped."
            ),
            mandatory_next_call=None,
            context={},
        )

    # ── Branch 12: all filled, notes done, confirmation not shown ────────────
    if _booking_complete(bc) and notes_state != "not_asked" and not bc.get("_confirmation_shown"):
        summary = render_confirmation_summary(bc)
        return GroundingDirective(
            action="SHOW_CONFIRMATION",
            directive=f"Mostrá este resumen EXACTO y pedí confirmación:\n{summary}",
            mandatory_next_call=None,
            context={
                "services": bc.get("last_services"),
                "stylist": bc.get("last_stylist"),
                "slot": bc.get("selected_slot"),
                "customer_name": bc.get("customer_name"),
                "notes": bc.get("notes"),
                "rendered_summary": summary,
            },
        )

    # ── Branch 13: fallback ──────────────────────────────────────────────────
    return GroundingDirective(
        action="ERROR_RECOVERY",
        directive=(
            "Estado inconsistente. "
            "Preguntá al cliente qué quiere hacer y lográ volver al flow."
        ),
        mandatory_next_call=None,
        context={"booking_context_keys": list(bc.keys())},
    )
