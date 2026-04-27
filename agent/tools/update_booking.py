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

from langchain_core.tools import tool

from agent.tools.schemas import ToolResponse

logger = logging.getLogger(__name__)


@tool
async def update_booking(
    services: list[str] | None = None,
    stylist_name: str | None = None,
    no_preference_stylist: bool = False,
    date_iso: str | None = None,
    audience: (
        Literal["adult_female", "adult_male", "child_female", "child_male", "baby", "unisex"] | None
    ) = None,
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
        audience: Audience qualifier for ambiguous service families.

    Returns:
        JSON-serialized ToolResponse with status, collected, missing, next_step.
    """
    try:
        return await _update_booking_impl(
            services=services,
            stylist_name=stylist_name,
            no_preference_stylist=no_preference_stylist,
            date_iso=date_iso,
            audience=audience,
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
) -> str:
    from agent.tools._booking_helpers import (
        _resolve_audience_variants,
        _resolve_service_ids,
        _resolve_stylist,
    )
    from database.connection import get_async_session

    async with get_async_session() as session:
        collected: dict = {}
        missing: list[str] = []
        errors: list[str] = []

        # ── Rule 2: no services ──────────────────────────────────────────────
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

        # ── Rule 1: audience disambiguation ───────────────────────────────────
        if audience is None:
            for service_name in services:
                family, variants = await _resolve_audience_variants(session, service_name)
                if len(variants) > 1:
                    logger.info(
                        "tool.response.rejected",
                        extra={"tool_name": "update_booking", "next_step": "audience_required"},
                    )
                    return ToolResponse(
                        status="rejected",
                        next_step="audience_required",
                        payload={"variants": variants, "family": family},
                    ).model_dump_json()

        collected["services"] = services
        collected["service_ids"] = resolved_ids

        # ── Rule 3: no stylist ────────────────────────────────────────────────
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

        # ── Rule 4: no date ───────────────────────────────────────────────────
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

        # ── Rule 5: all present → booking_ready ───────────────────────────────
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
