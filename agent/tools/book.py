"""
book — atomic booking tool.

Thin wrapper: parse args → validate guards → call BookingService → format ToolResponse.
All DB access is owned by BookingService. This tool holds no sessions.

GCal push fires AFTER DB commit inside BookingService (fire-and-forget).
Returns JSON-serialized ToolResponse.
"""

import logging
import re
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from langchain_core.tools import tool

from agent.services.booking_service import BookingService
from agent.tools.schemas import ToolResponse

logger = logging.getLogger(__name__)

_NOTES_MAX_LEN = 280
_NOTES_CTRL_RE = re.compile(r"[\x00-\x08\x0B-\x1F\x7F-\x9F]")
_NOTES_WS_RE = re.compile(r"\s+")


def _sanitize_notes(raw: str | None) -> str | None:
    """Strip control chars, collapse whitespace, cap length at 280 with ellipsis.

    Returns None for None/empty/whitespace-only input. Preserves \\t and \\n so
    they collapse to a single space via _NOTES_WS_RE rather than vanish silently.
    """
    if raw is None:
        return None
    without_ctrl = _NOTES_CTRL_RE.sub("", raw)
    collapsed = _NOTES_WS_RE.sub(" ", without_ctrl).strip()
    if not collapsed:
        return None
    if len(collapsed) > _NOTES_MAX_LEN:
        return collapsed[: _NOTES_MAX_LEN - 1] + "…"
    return collapsed


def _build_gcal_link(
    start: datetime,
    end: datetime,
    service_names: str,
    stylist_name: str,
    notes: str | None = None,
) -> str:
    """Build a Google Calendar deep-link pre-filled with appointment data.

    Converts start/end to UTC, encodes title/details/location via urllib.parse.quote.
    Returns a URL the customer can click to add the appointment to their calendar.
    """
    fmt = "%Y%m%dT%H%M%SZ"
    start_utc = start.astimezone(UTC).strftime(fmt)
    end_utc = end.astimezone(UTC).strftime(fmt)
    title = quote(f"{service_names} en Atrévete")
    detail_text = f"Turno con {stylist_name}"
    if notes:
        detail_text += f". {notes}"
    details = quote(detail_text)
    location = quote("Atrévete Salón de Belleza")
    return (
        f"https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={title}"
        f"&dates={start_utc}/{end_utc}"
        f"&details={details}"
        f"&location={location}"
    )


def _split_full_name(full_name: str) -> tuple[str, str | None]:
    """
    Split 'given_name first_surname [...]' on first whitespace.

    Returns (first_name, last_name).
    last_name is the remainder after the first token.
    Raises ValueError if name is empty or single-token (no surname).

    Decision #2887: customer name = given_name + first_surname.
    """
    stripped = full_name.strip()
    if not stripped:
        raise ValueError("El nombre del cliente está vacío.")
    parts = stripped.split(None, 1)  # split on first whitespace
    if len(parts) < 2:
        raise ValueError(
            f"El nombre '{stripped}' no incluye apellido. "
            "Se requiere al menos nombre y un apellido para registrar la cita."
        )
    first_name = parts[0]
    last_name = parts[1].strip() or None
    return first_name, last_name


@tool
async def book(
    service_ids: list[str],
    stylist_id: str,
    start_iso: str,
    customer_phone: str,
    customer_full_name: str,
    confirmed: bool = False,
    pre_book_validated: bool = False,
    notes: str | None = None,
) -> str:
    """
    Book an appointment atomically.

    Creates or reuses a customer by phone, inserts an Appointment,
    then fires a Google Calendar push (after DB commit, non-blocking).

    Args:
        service_ids: List of service UUID strings.
        stylist_id: Stylist UUID string.
        start_iso: Appointment start time in ISO 8601 format (timezone-aware).
        customer_phone: Customer phone in E.164 format.
        customer_full_name: Full name in 'FirstName LastName' format (surname required).
        confirmed: Must be True — the customer has explicitly confirmed the booking.
        pre_book_validated: Must be True — check_availability(slot_time=…) returned exact_match=True.
        notes: Optional appointment notes.

    Returns:
        JSON-serialized ToolResponse with payload containing:
        appointment_id, customer_id, start_iso, end_iso, stylist_id, calendar_link.
    """
    # --- Guard 1: confirmation required ---
    if not confirmed:
        logger.info(
            "tool.response.rejected",
            extra={"tool_name": "book", "next_step": "confirmation_required"},
        )
        return ToolResponse(
            status="rejected",
            next_step="confirmation_required",
            errors=["El cliente aún no ha confirmado la reserva explícitamente."],
        ).model_dump_json()

    # --- Guard 2: pre-book validation required ---
    if not pre_book_validated:
        logger.info(
            "tool.response.rejected",
            extra={"tool_name": "book", "next_step": "pre_book_validation_required"},
        )
        return ToolResponse(
            status="rejected",
            next_step="pre_book_validation_required",
            errors=[
                "Debes verificar que el hueco sigue disponible antes de reservar. "
                "Llama a check_availability(slot_time=…) y confirma exact_match=true."
            ],
        ).model_dump_json()

    # --- Guard 3: slot completeness ---
    missing: list[str] = []
    if not service_ids:
        missing.append("service_ids")
    if not stylist_id:
        missing.append("stylist_id")
    if not start_iso:
        missing.append("start_iso")
    if not customer_phone:
        missing.append("customer_phone")
    if not customer_full_name:
        missing.append("customer_full_name")
    if missing:
        logger.info(
            "tool.response.rejected",
            extra={"tool_name": "book", "next_step": "incomplete_booking", "missing": missing},
        )
        return ToolResponse(
            status="rejected",
            next_step="incomplete_booking",
            payload={"missing": missing},
            errors=[f"Faltan datos para completar la reserva: {', '.join(missing)}."],
        ).model_dump_json()

    # --- Sanitize customer-provided notes before any downstream use ---
    notes = _sanitize_notes(notes)

    # --- Validate full name (ADR-5: structured rejection instead of ValueError) ---
    from agent.tools.booking_helpers import _validate_full_name

    name_parts = _validate_full_name(customer_full_name)
    if name_parts is None:
        logger.info(
            "tool.response.rejected",
            extra={"tool_name": "book", "next_step": "name_required"},
        )
        return ToolResponse(
            status="rejected",
            next_step="name_required",
            errors=["Se requiere nombre y apellido para registrar la cita."],
        ).model_dump_json()
    first_name, last_name = name_parts

    # --- Parse UUIDs ---
    try:
        parsed_service_ids = [UUID(sid) for sid in service_ids]
        parsed_stylist_id = UUID(stylist_id)
    except (ValueError, AttributeError) as exc:
        return ToolResponse(
            status="rejected",
            errors=[f"Formato de UUID inválido: {exc}"],
        ).model_dump_json()

    # --- Parse start_time ---
    try:
        start_time = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=UTC)
    except ValueError as exc:
        return ToolResponse(
            status="rejected",
            errors=[f"El formato de start_iso es inválido: {exc}"],
        ).model_dump_json()

    # --- Delegate to BookingService (owns DB session + GCal push) ---
    result = await BookingService.create_appointment(
        service_ids=parsed_service_ids,
        stylist_id=parsed_stylist_id,
        start_at=start_time,
        customer_phone=customer_phone,
        first_name=first_name,
        last_name=last_name,
        notes=notes,
    )

    if not result.success:
        error_code = result.error_code or "error"
        if error_code == "duplicate":
            return ToolResponse(
                status="rejected",
                errors=["El horario solicitado ya está ocupado por otra cita con ese estilista."],
                next_step="reoffer_slots",
            ).model_dump_json()
        if error_code == "service_not_found":
            return ToolResponse(
                status="rejected",
                errors=[result.error_message or "No se encontraron los servicios solicitados."],
            ).model_dump_json()
        return ToolResponse(
            status="rejected",
            errors=[result.error_message or "La cita no pudo registrarse."],
            next_step="retry_later",
        ).model_dump_json()

    # --- Build calendar deep-link (pure function, no DB) ---
    calendar_link = _build_gcal_link(
        start=result.start_time,
        end=result.end_time,
        service_names=result.service_names or stylist_id,
        stylist_name=result.stylist_display_name or stylist_id,
        notes=notes,
    )

    return ToolResponse(
        status="ok",
        payload={
            "appointment_id": str(result.appointment_id),
            "customer_id": str(result.customer_id),
            "start_iso": result.start_time.isoformat(),
            "end_iso": result.end_time.isoformat(),
            "stylist_id": stylist_id,
            "calendar_link": calendar_link,
        },
    ).model_dump_json()
