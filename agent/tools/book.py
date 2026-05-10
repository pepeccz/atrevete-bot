"""
book — atomic booking tool.

Transaction: customer get-or-create + appointment insert + GCal push.
GCal push fires AFTER DB commit (fire-and-forget).
Rollback on any pre-commit failure.
Returns JSON-serialized ToolResponse.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID, uuid4

from langchain_core.tools import tool

from agent.services.customer_memory_service import read_customer_memories, write_customer_memories
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


async def _get_or_create_customer(
    session,
    phone: str,
    first_name: str,
    last_name: str | None,
) -> "Customer":  # type: ignore[name-defined]
    """
    Look up customer by phone. If not found, create and flush (no commit yet).
    Returns the Customer ORM object.
    """
    from sqlalchemy import select

    from database.models import Customer

    result = await session.execute(select(Customer).where(Customer.phone == phone))
    customer = result.scalar_one_or_none()
    if customer is None:
        customer = Customer(
            id=uuid4(),
            phone=phone,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(customer)
        await session.flush()  # get the ID without committing
    return customer


async def _fetch_service_duration(session, service_ids: list[UUID]) -> int:
    """Sum duration_minutes of given service IDs."""
    from sqlalchemy import select

    from database.models import Service

    result = await session.execute(
        select(Service.duration_minutes).where(Service.id.in_(service_ids))
    )
    rows = result.fetchall()
    if not rows:
        raise ValueError("No se encontraron los servicios solicitados.")
    return sum(row[0] for row in rows)


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
        appointment_id, customer_id, start_iso, end_iso, stylist_id.
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

    # --- Guard 2: slot completeness ---
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

    from sqlalchemy import select

    from agent.services.gcal_push_service import fire_and_forget_push_appointment
    from database.connection import get_async_session
    from database.models import Appointment, AppointmentStatus, Service, Stylist

    # --- Sanitize customer-provided notes before any downstream use ---
    notes = _sanitize_notes(notes)

    # --- Validate full name (ADR-5: structured rejection instead of ValueError) ---
    from agent.tools._booking_helpers import _validate_full_name

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

    # --- Atomic transaction ---
    appointment_id = uuid4()
    customer_id = None
    total_duration = 0

    try:
        async with get_async_session() as session:
            # Fetch service duration
            try:
                total_duration = await _fetch_service_duration(session, parsed_service_ids)
            except ValueError as exc:
                return ToolResponse(
                    status="rejected",
                    errors=[str(exc)],
                ).model_dump_json()

            end_time = start_time + timedelta(minutes=total_duration)

            # Get or create customer
            customer = await _get_or_create_customer(session, customer_phone, first_name, last_name)
            customer_id = customer.id

            # Insert appointment
            appointment = Appointment(
                id=appointment_id,
                customer_id=customer.id,
                stylist_id=parsed_stylist_id,
                service_ids=parsed_service_ids,
                start_time=start_time,
                duration_minutes=total_duration,
                status=AppointmentStatus.PENDING,
                first_name=first_name,
                last_name=last_name,
                notes=notes,
            )
            session.add(appointment)

            # Commit everything — DB is source of truth
            await session.commit()

    except Exception as exc:
        logger.error("book() transaction failed: %s", exc, exc_info=True)
        error_msg = str(exc)
        if (
            "duplicate" in error_msg.lower()
            or "unique" in error_msg.lower()
            or "exclusion" in error_msg.lower()
        ):
            return ToolResponse(
                status="rejected",
                errors=["El horario solicitado ya está ocupado por otra cita con ese estilista."],
                next_step="reoffer_slots",
            ).model_dump_json()
        return ToolResponse(
            status="rejected",
            errors=[f"La cita no pudo registrarse: {exc}"],
            next_step="retry_later",
        ).model_dump_json()

    # --- GCal push (fire-and-forget, AFTER commit) ---
    service_names = stylist_id  # fallback — overwritten below on success
    end_time = start_time + timedelta(minutes=total_duration)
    try:
        # Fetch service names for the GCal event title
        async with get_async_session() as session:
            svc_result = await session.execute(
                select(Service.name).where(Service.id.in_(parsed_service_ids))
            )
            service_names = ", ".join(row[0] for row in svc_result.fetchall())

        await fire_and_forget_push_appointment(
            appointment_id=appointment_id,
            stylist_id=parsed_stylist_id,
            customer_name=f"{first_name} {last_name or ''}".strip(),
            service_names=service_names,
            start_time=start_time,
            duration_minutes=total_duration,
            status="pending",
            notes=notes,
        )
    except Exception as exc:
        # GCal push failure does NOT undo the DB commit — fire-and-forget
        logger.error("GCal push failed (appointment already saved): %s", exc, exc_info=True)

    # --- Resolve stylist display name (used by memories + calendar link) ---
    stylist_display_name: str = stylist_id  # fallback to UUID string
    try:
        async with get_async_session() as session:
            sty = await session.get(Stylist, parsed_stylist_id)
            if sty is not None:
                stylist_display_name = sty.name
    except Exception as exc:
        logger.warning("Could not fetch stylist name: %s", exc)

    # --- Customer memory persistence (fire-and-forget, AFTER commit) ---
    async def _persist_memories_safe() -> None:
        try:
            existing = await read_customer_memories(customer_phone)
            await write_customer_memories(
                phone=customer_phone,
                booking_data={
                    "service_names": service_names.split(", ") if service_names else [],
                    "stylist_name": stylist_display_name,
                    "stylist_id": stylist_id,
                    "no_preference_stylist": False,
                    "start_time": start_time.isoformat(),
                    "notes": notes,
                },
                existing_prefs=existing,
            )
        except Exception as exc:
            logger.warning(
                "customer_memory persistence failed (booking already committed): %s",
                exc,
                exc_info=True,
            )

    asyncio.create_task(_persist_memories_safe())

    calendar_link = _build_gcal_link(
        start=start_time,
        end=end_time,
        service_names=service_names,
        stylist_name=stylist_display_name,
        notes=notes,
    )

    return ToolResponse(
        status="ok",
        payload={
            "appointment_id": str(appointment_id),
            "customer_id": str(customer_id),
            "start_iso": start_time.isoformat(),
            "end_iso": end_time.isoformat(),
            "stylist_id": stylist_id,
            "calendar_link": calendar_link,
        },
    ).model_dump_json()
