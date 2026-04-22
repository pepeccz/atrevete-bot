"""Booking leaf SystemMessage builder — booking-prompts-audit-fix.

Public API
----------
build_leaf_system_message(step, booking, state) -> SystemMessage
    Async. Builds a SystemMessage prepended to every booking leaf LLM call.
    Includes: persona, step-specific instruction, catalog, business hours,
    audience taxonomy, and current booking snapshot.
    Degrades gracefully when catalog or hours are unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage

from agent.prompts.business_hours import load_business_hours_snapshot
from agent.prompts.catalog_builder import build_catalog_prompt_section

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persona block
# ---------------------------------------------------------------------------

_PERSONA = (
    "Eres Maite, la asistente virtual del salón de belleza Atrévete. "
    "Tu rol es guiar al cliente paso a paso para reservar un turno. "
    "Respondes siempre en español de España (castellano peninsular), de forma cálida y profesional."
)

# ---------------------------------------------------------------------------
# Audience taxonomy — señora→adult_female, caballero→adult_male, niño→child, bebé→baby
# ---------------------------------------------------------------------------

_AUDIENCE_TAXONOMY = """
TAXONOMÍA DE AUDIENCIA (usa estos valores exactos al extraer):
  señora / mujer / femenino     → adult_female
  caballero / hombre / masculino → adult_male
  niña                           → child_female
  niño                           → child_male
  bebé / bebe / nene / nena      → baby
  unisex / para todos            → unisex
""".strip()

# ---------------------------------------------------------------------------
# Per-step extraction instructions
# ---------------------------------------------------------------------------

_STEP_INSTRUCTIONS: dict[str, str] = {
    "ask_service": (
        "PASO ACTUAL: Identifica qué servicio/s quiere el cliente. "
        "Extrae los IDs de los servicios del catálogo. "
        "Si hay ambigüedad pregunta para aclarar. No preguntes por la audiencia en este paso."
    ),
    "ask_audience": (
        "PASO ACTUAL: Identifica para quién es el servicio (audiencia). "
        "Usa la taxonomía de audiencia para mapear la respuesta del cliente al valor correcto. "
        "Si el cliente dice 'bebé' o 'bebe', el valor es 'baby'."
    ),
    "ask_stylist": (
        "PASO ACTUAL: Pregunta con qué estilista prefiere el cliente. "
        "Si el cliente dice que no tiene preferencia, marca no_preference=true."
    ),
    "ask_date": (
        "PASO ACTUAL: Identifica la fecha deseada para el turno. "
        "Convierte referencias relativas (mañana, el jueves, etc.) a una fecha concreta YYYY-MM-DD. "
        "Consulta el horario de negocio para verificar que el día tiene atención."
    ),
    "ask_slot": (
        "PASO ACTUAL: Muestra los turnos disponibles al cliente y pide que elija uno. "
        "Extrae el índice (0-based) del turno seleccionado de la lista ofrecida."
    ),
    "ask_name": (
        "PASO ACTUAL: Pide el nombre completo del cliente para registrar el turno. "
        "Extrae nombre de pila y primer apellido."
    ),
    "ask_notes": (
        "PASO ACTUAL: Pregunta si el cliente tiene alguna nota o solicitud especial "
        "(alergias, preferencias de producto, etc.). "
        "Si no tiene nada especial, marca user_declined=true."
    ),
}

_DEFAULT_INSTRUCTION = "PASO ACTUAL: Asiste al cliente en el proceso de reserva."


# ---------------------------------------------------------------------------
# Booking snapshot formatter
# ---------------------------------------------------------------------------


def _format_booking_snapshot(booking: dict[str, Any]) -> str:
    """Return a compact booking snapshot string."""
    lines = ["RESERVA ACTUAL:"]
    service_ids = booking.get("service_ids")
    if service_ids:
        lines.append(f"  Servicios: {', '.join(str(s) for s in service_ids)}")
    audience = booking.get("audience")
    if audience:
        lines.append(f"  Audiencia: {audience}")
    stylist_id = booking.get("stylist_id")
    if stylist_id:
        lines.append(f"  Estilista: {stylist_id}")
    elif booking.get("no_preference"):
        lines.append("  Estilista: sin preferencia")
    appt_date = booking.get("date")
    if appt_date:
        lines.append(f"  Fecha: {appt_date}")
    selected_slot = booking.get("selected_slot")
    if selected_slot:
        lines.append(f"  Turno: {selected_slot}")
    name = booking.get("customer_full_name")
    if name:
        lines.append(f"  Nombre: {name}")
    step = booking.get("step")
    if step:
        lines.append(f"  Paso actual: {step}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hours formatter
# ---------------------------------------------------------------------------


def _format_hours(hours: dict[str, str]) -> str:
    if not hours:
        return ""
    lines = ["HORARIOS DEL SALÓN:"]
    for day, value in hours.items():
        lines.append(f"  {day}: {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


async def build_leaf_system_message(
    step: str,
    booking: dict[str, Any] | None,
    state: dict[str, Any],
) -> SystemMessage:
    """Build the SystemMessage for a booking leaf LLM call.

    Args:
        step: The leaf step name (e.g. 'ask_service', 'ask_audience').
        booking: Current booking context dict, or None on first turn.
        state: Full agent state (reserved for future extension).

    Returns:
        SystemMessage with persona, step instruction, catalog, hours,
        audience taxonomy, and booking snapshot (if booking is not None).
    """
    # Load catalog
    catalog_section = await build_catalog_prompt_section()
    if not catalog_section:
        logger.warning("Catalog is empty or unavailable for leaf step '%s'", step)

    # Load business hours
    hours = await load_business_hours_snapshot()

    # Assemble sections
    sections: list[str] = [_PERSONA]

    # Step instruction
    instruction = _STEP_INSTRUCTIONS.get(step, _DEFAULT_INSTRUCTION)
    sections.append(instruction)

    # Catalog (skip if empty — graceful degradation)
    if catalog_section:
        sections.append(f"CATÁLOGO DE SERVICIOS:\n{catalog_section}")

    # Business hours
    hours_text = _format_hours(hours)
    if hours_text:
        sections.append(hours_text)

    # Audience taxonomy (always included)
    sections.append(_AUDIENCE_TAXONOMY)

    # Booking snapshot (only when booking is provided)
    if booking is not None:
        sections.append(_format_booking_snapshot(booking))

    content = "\n\n".join(sections)
    return SystemMessage(content=content)
