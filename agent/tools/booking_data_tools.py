"""
Booking Data Tools — Persist booking data collected during conversation.

update_booking is a single tool that persists services, stylist, customer name,
and notes to booking_context. It validates inputs, resolves DB entities, and
returns a patch dict that booking_mode applies via _post_tool_result.

The tool is stateless — it receives the current context via _current_context
(injected by _pre_tool_call) and returns a _booking_context_patch dict.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from database.connection import get_async_session

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

_NO_PREF_PHRASES = frozenset(
    {
        "sin preferencia",
        "me da igual",
        "cualquiera",
        "la primera disponible",
        "no tengo preferencia",
        "da lo mismo",
        "no me importa",
        "la que sea",
        "el que sea",
        "la primera con disponibilidad",
    }
)

_NAME_BLOCKLIST = frozenset(
    {
        "cliente",
        "usuario",
        "desconocido",
        "n/a",
        "nombre",
        "sin nombre",
        "no proporcionado",
        "unknown",
        "user",
        "customer",
    }
)

_NOTES_NO_VALUES = frozenset({"no", "ninguna", "sin notas", "nada", "ninguno"})


# ============================================================================
# Pydantic Schema
# ============================================================================


class UpdateBookingSchema(BaseModel):
    """Schema for update_booking tool parameters.

    All fields are optional — the LLM calls this tool with whichever
    fields it has collected from the conversation so far.
    """

    services: list[str] | None = Field(
        default=None,
        description="Lista de nombres exactos de servicios del catálogo",
    )
    stylist_name: str | None = Field(
        default=None,
        description=(
            "Nombre de la estilista elegida, o 'sin preferencia' / 'me da igual' / "
            "'cualquiera' si no tiene preferencia"
        ),
    )
    customer_first_name: str | None = Field(
        default=None,
        description="Nombre del cliente (ej: 'Pablo')",
    )
    customer_last_name: str | None = Field(
        default=None,
        description="Primer apellido del cliente (ej: 'García')",
    )
    notes: str | None = Field(
        default=None,
        description="Notas para la estilista (ej: alergias, preferencias). 'no' = sin notas",
    )
    slot_index: int | None = Field(
        default=None,
        description=(
            "Índice (1-based) del slot elegido por el cliente de la lista ofrecida "
            "por check_availability. Úsalo cuando el cliente seleccione un horario "
            "ANTES de llamar a book(). Ej: si el cliente dice '2', pasa slot_index=2."
        ),
    )
    clear_slot: bool | None = Field(
        default=None,
        description="Pon true para limpiar el horario seleccionado y buscar otro día/hora.",
    )


# ============================================================================
# Helpers
# ============================================================================


async def _find_similar_services(name: str) -> list[str]:
    """Find service names containing the input (for ambiguity guidance)."""
    from agent.utils.fuzzy_resolver import normalize_spanish
    from database.connection import get_async_session
    from database.models import Service
    from sqlalchemy import select

    normalized = normalize_spanish(name)
    async with get_async_session() as session:
        result = await session.execute(
            select(Service.name).where(Service.is_active == True)
        )
        all_names = [row[0] for row in result.all()]

    return [
        n for n in all_names if normalized in normalize_spanish(n)
    ][:5]


async def _find_audience_siblings_for_signal(svc: Any) -> list[str]:
    """Return names of services that share the base word but have different audience.

    Informational only — never raised as an error. Used by update_booking to populate
    _audience_ambiguity in _booking_context_patch when the user may have under-specified.
    """
    from database.models import Service
    from sqlalchemy import select

    base_word = svc.name.split()[0].lower() if svc.name else ""
    if not base_word:
        return []
    async with get_async_session() as session:
        result = await session.execute(
            select(Service.id, Service.name, Service.audience).where(
                Service.audience.is_not(None),
                Service.id != svc.id,
                Service.is_active.is_(True),
            )
        )
        rows = result.all()
    return [row[1] for row in rows if row[1].split()[0].lower() == base_word]


def _build_response(
    ctx: dict[str, Any],
    success: bool,
    validation_errors: list[str] | None = None,
) -> dict[str, Any]:
    """Build a structured response summarising current booking state.

    Args:
        ctx: The effective booking context (after applying changes).
        success: Whether the update was accepted without errors.
        validation_errors: List of human-readable error strings (if any).

    Returns:
        Dict with collected, missing, next_step, success, errors.
    """
    collected: list[str] = []
    missing: list[str] = []

    if ctx.get("last_services"):
        collected.append(f"servicios: {', '.join(ctx['last_services'])}")
    else:
        missing.append("servicio")

    if ctx.get("last_services") and not ctx.get("add_more_asked"):
        missing.append("preguntar ¿algo más?")

    if ctx.get("last_stylist") or ctx.get("no_preference_stylist"):
        stylist = ctx.get("last_stylist", "Sin preferencia")
        collected.append(f"estilista: {stylist}")
    else:
        missing.append("estilista")

    if ctx.get("selected_slot"):
        slot = ctx["selected_slot"]
        collected.append(f"horario: {slot.get('date', '?')} a las {slot.get('time', '?')}")
    else:
        missing.append("fecha/hora")

    if ctx.get("customer_name"):
        collected.append(f"nombre: {ctx['customer_name']}")
    else:
        missing.append("nombre")

    if ctx.get("notes_asked"):
        notes = ctx.get("notes")
        collected.append(f"notas: {notes or '(sin notas)'}")
    else:
        missing.append("notas")

    # Determine next step
    if missing:
        next_step = f"Falta: {missing[0]}"
    else:
        next_step = "Todos los datos recogidos — muestra resumen y pide confirmación"

    # Audience ambiguity signal — propagate through tool response fields so the
    # LLM reads it on the SAME turn (the system_message is cached at construction;
    # the <audience_ambiguity> XML tag only renders on turn N+1 via dynamic context
    # refresh). Using descriptive-state form — no imperative verbs.
    ambiguity = ctx.get("_audience_ambiguity")
    if ambiguity and not ctx.get("service_audience_hint"):
        variants_str = ", ".join(ambiguity.get("variants", []))
        next_step = (
            f"Audiencia ambigua: familia {ambiguity.get('family', '')}, "
            f"variantes {variants_str}. "
            f"Falta confirmar variante antes de avanzar."
        )
        if "audiencia" not in missing:
            missing.append("audiencia")

    return {
        "success": success,
        "collected": collected,
        "missing": missing,
        "next_step": next_step,
        "errors": validation_errors or [],
    }


# ============================================================================
# Tool
# ============================================================================


@tool(args_schema=UpdateBookingSchema)
async def update_booking(
    services: list[str] | None = None,
    stylist_name: str | None = None,
    customer_first_name: str | None = None,
    customer_last_name: str | None = None,
    notes: str | None = None,
    slot_index: int | None = None,
    clear_slot: bool | None = None,
    _current_context: dict | None = None,
) -> dict[str, Any]:
    """Persist booking data collected from the conversation.

    ⚠️ IMPORTANT: Pass ONLY the field(s) that changed — do NOT re-send
    fields already collected. Each call is INCREMENTAL.

    Call this tool AFTER resolving each piece of booking data:
    - Service identified → update_booking(services=["nombre exacto"])
    - Stylist chosen → update_booking(stylist_name="nombre") or "sin preferencia"
    - Slot selected → update_booking(slot_index=2)  ← ONLY slot_index, nothing else
    - Name given → update_booking(customer_first_name="Pablo", customer_last_name="García")
    - Notes → update_booking(notes="texto") or notes="no" for none

    ❌ WRONG: update_booking(services=["Cortar"], slot_index=2)  ← re-sends services!
    ✅ RIGHT: update_booking(slot_index=2)  ← only the new field

    Returns current booking state summary and a _booking_context_patch
    for the mode node to apply.
    """
    ctx = dict(_current_context or {})
    patch: dict[str, Any] = {}
    errors: list[str] = []

    # ── Services branch ──────────────────────────────────────────────────
    if services is not None:
        from agent.tools.availability_tools import (
            _resolve_service_by_name,
            _get_active_stylists_for_category,
        )

        resolved_services = []
        resolved_names = []
        for svc_name in services:
            svc = await _resolve_service_by_name(svc_name)
            if svc is None:
                # Find similar names to guide the LLM
                candidates = await _find_similar_services(svc_name)
                if candidates:
                    names = ", ".join(candidates)
                    errors.append(
                        f"Servicio '{svc_name}' no encontrado. "
                        f"Variantes similares en el catálogo: {names}"
                    )
                else:
                    errors.append(f"Servicio '{svc_name}' no encontrado en el catálogo.")
                continue

            resolved_services.append(svc)
            resolved_names.append(svc.name)

        if resolved_services:
            # Validate category consistency
            categories = {svc.category for svc in resolved_services}
            if len(categories) > 1:
                cat_labels = ", ".join(c.value for c in categories)
                errors.append(
                    f"No se pueden combinar servicios de categorías distintas ({cat_labels}). "
                    "Ofrece dos citas separadas."
                )
            else:
                category = resolved_services[0].category
                total_duration = sum(svc.duration_minutes for svc in resolved_services)

                patch["last_services"] = resolved_names
                patch["last_service_category"] = category.value
                patch["last_total_duration_minutes"] = total_duration

                # Cascade clear ONLY when services actually changed
                old_services = ctx.get("last_services") or []
                if set(resolved_names) != set(old_services):
                    patch["offered_slots"] = None
                    patch["selected_slot"] = None

                    # Category change + existing stylist → check compatibility
                    old_category = ctx.get("last_service_category")
                    if old_category and old_category != category.value and ctx.get("last_stylist"):
                        patch["last_stylist"] = None
                        patch["no_preference_stylist"] = None

                # Include available stylists on first service resolution
                if not ctx.get("_offered_stylists"):
                    stylists = await _get_active_stylists_for_category(category)
                    if stylists:
                        stylist_names = [s.name for s in stylists]
                        patch["_offered_stylists"] = stylist_names + ["Sin preferencia"]
                        patch["available_stylists"] = stylist_names

                # Apply service changes to effective context
                ctx.update({k: v for k, v in patch.items() if v is not None})

        # Informational audience ambiguity signal (non-blocking)
        if resolved_services and not ctx.get("service_audience_hint"):
            for svc in resolved_services:
                if svc.audience is not None:
                    siblings = await _find_audience_siblings_for_signal(svc)
                    if siblings:
                        ambiguity_data = {
                            "family": svc.name.split()[0].capitalize(),
                            "resolved_as": svc.name,
                            "resolved_audience": svc.audience,
                            "variants": [svc.name, *siblings],
                        }
                        patch["_audience_ambiguity"] = ambiguity_data
                        # Mirror into ctx so _build_response sees it on this turn
                        ctx["_audience_ambiguity"] = ambiguity_data
                        break  # first ambiguous service wins

    # ── Stylist branch ───────────────────────────────────────────────────
    if stylist_name is not None:
        from agent.tools.availability_tools import _resolve_stylist_by_name

        name_clean = stylist_name.strip()
        if name_clean.lower() in _NO_PREF_PHRASES:
            patch["no_preference_stylist"] = True
            patch["last_stylist"] = "Sin preferencia"
            # Cascade clear slots on stylist change
            if ctx.get("last_stylist") and ctx.get("last_stylist") != "Sin preferencia":
                patch["offered_slots"] = None
                patch["selected_slot"] = None
            ctx["last_stylist"] = "Sin preferencia"
            ctx["no_preference_stylist"] = True
        else:
            resolved = await _resolve_stylist_by_name(name_clean)
            if resolved is None:
                errors.append(f"Estilista '{name_clean}' no encontrada en el catálogo.")
            else:
                # Check category compatibility
                from database.models import ServiceCategory

                svc_cat_val = ctx.get("last_service_category")
                if svc_cat_val:
                    stylist_cat = resolved.category.value if hasattr(resolved.category, "value") else resolved.category
                    compatible = (
                        stylist_cat == svc_cat_val
                        or stylist_cat == ServiceCategory.BOTH.value
                    )
                    if not compatible:
                        errors.append(
                            f"{resolved.name} no realiza servicios de {svc_cat_val}. "
                            "Elige una estilista compatible."
                        )
                    else:
                        old_stylist = ctx.get("last_stylist")
                        patch["last_stylist"] = resolved.name
                        patch["no_preference_stylist"] = None
                        # Cascade clear slots on stylist change
                        if old_stylist and old_stylist != resolved.name:
                            patch["offered_slots"] = None
                            patch["selected_slot"] = None
                        ctx["last_stylist"] = resolved.name
                else:
                    # No category yet — accept stylist anyway
                    old_stylist = ctx.get("last_stylist")
                    patch["last_stylist"] = resolved.name
                    patch["no_preference_stylist"] = None
                    if old_stylist and old_stylist != resolved.name:
                        patch["offered_slots"] = None
                        patch["selected_slot"] = None
                    ctx["last_stylist"] = resolved.name

    # ── Customer name branch ─────────────────────────────────────────────
    if customer_first_name is not None:
        first = customer_first_name.strip()
        last = (customer_last_name or "").strip()
        if first.lower() in _NAME_BLOCKLIST:
            errors.append(
                f"Nombre rechazado: '{first}' parece un placeholder. "
                "Pregunta el nombre real al cliente."
            )
        else:
            patch["customer_first_name"] = first
            patch["customer_last_name"] = last or None
            full_name = f"{first} {last}" if last else first
            patch["customer_name"] = full_name
            ctx["customer_name"] = full_name
            ctx["customer_first_name"] = first
            ctx["customer_last_name"] = last or None

    # ── Notes branch ─────────────────────────────────────────────────────
    if notes is not None:
        if notes.strip().lower() in _NOTES_NO_VALUES:
            patch["notes"] = None
        else:
            patch["notes"] = notes.strip()
        patch["notes_asked"] = True
        ctx["notes_asked"] = True
        ctx["notes"] = patch.get("notes")

    # ── Slot index branch ────────────────────────────────────────────────
    if slot_index is not None:
        offered_slots: list[dict] = ctx.get("offered_slots") or []
        if not offered_slots:
            errors.append(
                "No hay slots ofrecidos en el contexto actual. "
                "Llama primero a check_availability para obtener disponibilidad."
            )
        else:
            try:
                idx = int(slot_index)
                if 1 <= idx <= len(offered_slots):
                    slot = offered_slots[idx - 1]
                    selected: dict[str, Any] = {
                        "stylist_name": slot.get("stylist_name"),
                        "stylist_id": slot.get("stylist_id"),
                        "start_time": slot.get("start_time") or slot.get("full_datetime"),
                        "end_time": slot.get("end_time"),
                        "date": slot.get("date"),
                        "time": slot.get("time"),
                    }
                    patch["selected_slot"] = selected
                    ctx["selected_slot"] = selected
                    # Keep last_stylist in sync with selected slot
                    if slot.get("stylist_name") and not ctx.get("last_stylist"):
                        patch["last_stylist"] = slot["stylist_name"]
                        ctx["last_stylist"] = slot["stylist_name"]
                else:
                    errors.append(
                        f"slot_index {idx} fuera de rango (1-{len(offered_slots)}). "
                        "Mostrá la lista de horarios disponibles de nuevo."
                    )
            except (ValueError, TypeError):
                errors.append("slot_index debe ser un número entero válido.")

    # ── Clear slot branch ────────────────────────────────────────────────
    if clear_slot:
        patch["selected_slot"] = None
        patch["offered_slots"] = None
        ctx.pop("selected_slot", None)
        ctx.pop("offered_slots", None)

    # ── Build response ───────────────────────────────────────────────────
    success = len(errors) == 0
    response = _build_response(ctx, success, errors if errors else None)
    response["_booking_context_patch"] = patch
    return response
