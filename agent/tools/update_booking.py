"""Slot collector tool for the booking flow.

Accepts any subset of booking slots, validates them against the DB, and returns
a ToolResponse describing which slots were collected and which are still missing.
Idempotent: safe to call repeatedly. Does NOT create appointments.

Priority matrix (first matching rule wins):
1. Ambiguous service family + no audience → rejected, audience_required
2. No services → partial, service_required
3. Services present + no stylist + no_preference=False → partial, stylist_required
4. Services + stylist + no date → partial, date_required
5. All present → ok, booking_ready

Refs: R2, R3, design §5
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from agent.tools.schemas import ToolResponse

_MADRID_TZ = ZoneInfo("Europe/Madrid")

logger = logging.getLogger(__name__)


@tool
async def update_booking(
    services: list[str] | None = None,
    stylist_name: str | None = None,
    no_preference_stylist: bool = False,
    date_iso: str | None = None,
    date_text: str | None = None,
    audience: (
        Literal["adult_female", "adult_male", "child_female", "child_male", "baby", "unisex"] | None
    ) = None,
    customer_full_name: str | None = None,
    notes: str | None = None,
    no_more_services: bool = False,
    extras_asked: bool = False,
    notes_asked: bool = False,
    customer_known: bool = False,
) -> str:
    """Slot collector for the booking flow.

    Pass any subset of booking slots; returns what was collected, what is missing,
    and the next descriptive state in `next_step`. Safe to call repeatedly —
    idempotent. Does NOT create appointments; call `book` (with confirmed=True) for that.

    Args:
        services: List of service names requested (e.g. ["corte dama", "peinado"]).
        stylist_name: Human-readable stylist name (e.g. "Marta"). Resolved to ID internally.
        no_preference_stylist: Set True if customer has no stylist preference.
        date_iso: Desired appointment date as ISO date string (YYYY-MM-DD).
        date_text: Literal relative date phrase from the user (e.g. "mañana",
            "el miércoles que viene"). Use when date_iso is not available.
            The backend resolves it against the current Europe/Madrid date.
            Use one or the other — if date_iso is set, date_text is ignored.
        audience: Audience qualifier for ambiguous service families.
        customer_full_name: Customer full name in 'FirstName LastName' format. Required when
            customer is unknown. If <customer> block has a Nombre: line, pass that value here.
        notes: Optional appointment notes provided by the customer.
        no_more_services: Set True when the customer confirmed they don't want additional services.
        extras_asked: Round-trip flag. Pass back the value from previous collected.extras_asked.
        notes_asked: Round-trip flag. Pass back the value from previous collected.notes_asked.
        customer_known: Set True when <customer> block contains a 'Nombre:' line (returning customer).

    Returns:
        JSON-serialized ToolResponse with status, collected, missing, next_step.
    """
    try:
        return await _update_booking_impl(
            services=services,
            stylist_name=stylist_name,
            no_preference_stylist=no_preference_stylist,
            date_iso=date_iso,
            date_text=date_text,
            audience=audience,
            customer_full_name=customer_full_name,
            notes=notes,
            no_more_services=no_more_services,
            extras_asked=extras_asked,
            notes_asked=notes_asked,
            customer_known=customer_known,
        )
    except Exception as exc:
        logger.error("update_booking unhandled exception: %s", exc, exc_info=True)
        return ToolResponse(
            status="rejected",
            next_step="retry_later",
            errors=[f"internal: {type(exc).__name__}"],
        ).model_dump_json()


async def _update_booking_impl(
    services: list[str] | None,
    stylist_name: str | None,
    no_preference_stylist: bool,
    date_iso: str | None,
    audience: str | None,
    date_text: str | None = None,
    customer_full_name: str | None = None,
    notes: str | None = None,
    no_more_services: bool = False,
    extras_asked: bool = False,
    notes_asked: bool = False,
    customer_known: bool = False,
) -> str:
    from agent.tools._booking_helpers import (
        _resolve_audience_variants,
        _resolve_service_ids,
        _resolve_stylist,
        _validate_full_name,
    )
    from database.connection import get_async_session

    async with get_async_session() as session:
        collected: dict = {}
        missing: list[str] = []
        errors: list[str] = []

        # ── Step 3: no services ───────────────────────────────────────────────
        if not services:
            missing.append("services")
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=missing,
                next_step="service_required",
            ).model_dump_json()

        # ── Resolve service names ─────────────────────────────────────────────
        resolved_ids, unknown_names = await _resolve_service_ids(session, services)

        if unknown_names:
            errors.extend([f"No reconozco el servicio: {n}" for n in unknown_names])
            logger.info(
                "tool.response.rejected",
                extra={
                    "tool_name": "update_booking",
                    "next_step": "service_required",
                    "errors": errors,
                },
            )
            return ToolResponse(
                status="rejected",
                missing=["services"],
                next_step="service_required",
                errors=errors,
            ).model_dump_json()

        # ── Steps 1+2: audience / variant disambiguation ──────────────────────
        # kind=="audience" → multi-PRINCIPAL same-dimension, ask for audience.
        # kind=="variant"  → multi-VARIANT same-parent, ask for variant.
        if audience is None:
            for service_name in services:
                kind, family, candidates = await _resolve_audience_variants(session, service_name)
                if kind == "audience":
                    logger.info(
                        "tool.response.rejected",
                        extra={"tool_name": "update_booking", "next_step": "audience_required"},
                    )
                    return ToolResponse(
                        status="rejected",
                        next_step="audience_required",
                        payload={"variants": candidates, "family": family},
                    ).model_dump_json()
                if kind == "variant":
                    logger.info(
                        "tool.response.rejected",
                        extra={"tool_name": "update_booking", "next_step": "variant_required"},
                    )
                    return ToolResponse(
                        status="rejected",
                        next_step="variant_required",
                        payload={"variants": candidates, "family": family},
                    ).model_dump_json()

        collected["services"] = services
        collected["service_ids"] = resolved_ids

        # ── Step 4: extras loop — must be asked before stylist (ADR-2) ────────
        if len(services) >= 1 and not no_more_services and not extras_asked:
            collected["extras_asked"] = True
            logger.info(
                "tool.response.partial",
                extra={"tool_name": "update_booking", "next_step": "extras_loop_required"},
            )
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=[],
                next_step="extras_loop_required",
            ).model_dump_json()

        # Carry round-trip flags into collected (so LLM can pass them back)
        collected["extras_asked"] = True  # gate is closed at this point
        if no_more_services:
            collected["no_more_services"] = True

        # ── Step 5: no stylist ────────────────────────────────────────────────
        stylist_id = None
        if stylist_name is not None:
            stylist_id = await _resolve_stylist(session, stylist_name)
            if stylist_id is None:
                logger.info(
                    "tool.response.rejected",
                    extra={"tool_name": "update_booking", "next_step": "stylist_required"},
                )
                return ToolResponse(
                    status="rejected",
                    collected=collected,
                    missing=["stylist"],
                    next_step="stylist_required",
                    errors=[f"No encontré a la estilista: {stylist_name}"],
                ).model_dump_json()
            collected["stylist_id"] = str(stylist_id)
            collected["stylist_name"] = stylist_name

        if not no_preference_stylist and stylist_id is None:
            missing.append("stylist")
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=missing,
                next_step="stylist_required",
            ).model_dump_json()

        if no_preference_stylist:
            collected["no_preference_stylist"] = True

        # ── Step 6: date_text resolution ──────────────────────────────────────
        if not date_iso and date_text:
            from agent.booking.resolvers.time_resolver import resolve_relative_date

            today_local = datetime.now(_MADRID_TZ).date()
            resolved = resolve_relative_date(date_text, today_local)
            if resolved is not None:
                date_iso = resolved.isoformat()
            else:
                return ToolResponse(
                    status="partial",
                    collected=collected,
                    missing=["date_iso"],
                    next_step="date_clarification_required",
                    errors=[f"No pude entender la fecha: {date_text}"],
                ).model_dump_json()

        # ── Step 6b: no date ──────────────────────────────────────────────────
        if not date_iso:
            missing.append("date_iso")
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=missing,
                next_step="date_required",
            ).model_dump_json()

        # Validate date format
        try:
            datetime.fromisoformat(date_iso)
            collected["date_iso"] = date_iso
        except ValueError:
            return ToolResponse(
                status="rejected",
                collected=collected,
                missing=["date_iso"],
                next_step="date_required",
                errors=[f"Fecha inválida: {date_iso}"],
            ).model_dump_json()

        # ── Step 7: name required — after stylist+date, after extras loop ─────
        name_resolved = bool(_validate_full_name(customer_full_name)) or customer_known
        if not name_resolved:
            logger.info(
                "tool.response.partial",
                extra={"tool_name": "update_booking", "next_step": "name_required"},
            )
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=["customer_full_name"],
                next_step="name_required",
            ).model_dump_json()

        if customer_full_name:
            collected["customer_full_name"] = customer_full_name

        # ── Step 8: notes offered once ────────────────────────────────────────
        if not notes_asked:
            collected["notes_asked"] = True
            logger.info(
                "tool.response.partial",
                extra={"tool_name": "update_booking", "next_step": "notes_optional"},
            )
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=[],
                next_step="notes_optional",
            ).model_dump_json()

        collected["notes_asked"] = True
        if notes is not None:
            collected["notes"] = notes

        # ── Step 9: all gates pass → booking_ready ────────────────────────────
        logger.info(
            "tool.response.complete",
            extra={"tool_name": "update_booking", "payload_keys": list(collected.keys())},
        )
        return ToolResponse(
            status="ok",
            collected=collected,
            missing=[],
            next_step="booking_ready",
        ).model_dump_json()
