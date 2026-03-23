"""
Tool Result Extractors for BookingModeV7.

Pure functions that extract canonical fields from tool responses into
BookingContextV7. They do NOT make flow decisions — that's the LLM's job.

Each extractor:
- Receives a parsed dict (tool result) and a BookingContextV7
- Mutates the context in place
- Never raises — fails silently with logging
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from agent.modes.booking_context_v7 import BookingContextV7

logger = logging.getLogger(__name__)

# ============================================================================
# Audience hint extraction (ported from booking_mode.py)
# ============================================================================

_AUDIENCE_HINT_MAP: dict[str, str] = {
    "caballero": "adult_male",
    "hombre": "adult_male",
    "adulto": "adult_male",
    "dama": "adult_female",
    "mujer": "adult_female",
    "adulta": "adult_female",
    "nino": "child_male",
    "nene": "child_male",
    "nina": "child_female",
    "nena": "child_female",
    "bebe": "baby",
}


def _normalize_text(value: str | None) -> str:
    """Unicode NFKD normalization, lowercase, strip accents."""
    raw = (value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def extract_service_audience_hint(value: str | None) -> str | None:
    """Extract audience hint from a service name string.

    Scans the normalized text for known audience tokens and returns the
    corresponding hint (e.g. "adult_male", "adult_female").
    """
    normalized = _normalize_text(value)
    if not normalized:
        return None

    for token, hint in _AUDIENCE_HINT_MAP.items():
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            return hint

    return None


# ============================================================================
# Pre-resolvers (called before prompt building)
# ============================================================================


def resolve_pending_clarification(ctx: BookingContextV7) -> bool:
    """Attempt to resolve a pending audience clarification using service_audience_hint.

    Called as a pre-resolver in BookingModeV7.handle() AFTER _resolve_audience_hint()
    and BEFORE _build_messages(). If the pending clarification axis is "audience" and
    service_audience_hint matches one of the options, this function MUTATES ctx:
    - Sets service_id, service_name, service_category, service_duration_minutes
    - Appends to selected_services (NOT overwrite)
    - Clears pending_clarification and candidate_services
    Returns True if resolution happened, False otherwise.
    """
    if ctx.pending_clarification is None:
        return False
    if ctx.pending_clarification.get("axis") != "audience":
        return False
    if ctx.service_audience_hint is None:
        return False

    hint_lower = _normalize_text(ctx.service_audience_hint)
    options = ctx.pending_clarification.get("options", [])

    for opt in options:
        val = _normalize_text(opt.get("value"))
        label = _normalize_text(opt.get("label"))
        if hint_lower in val or val in hint_lower or hint_lower in label:
            ctx.service_id = str(opt["service_id"])
            ctx.service_name = opt["service_name"]
            ctx.service_category = opt.get("category")
            ctx.service_duration_minutes = opt.get("duration_minutes")
            ctx.service_family = opt.get("family")
            # APPEND, not overwrite (same pattern as Shape 1 lines 115-118)
            if opt["service_name"] not in ctx.selected_services:
                ctx.selected_services = [opt["service_name"]] + [
                    s for s in ctx.selected_services if s != opt["service_name"]
                ]
            ctx.pending_clarification = None
            ctx.candidate_services = []
            logger.info(
                "resolve_pending_clarification: auto-resolved '%s' via audience hint '%s'",
                opt["service_name"],
                ctx.service_audience_hint,
            )
            return True

    return False


# ============================================================================
# Safe parsing
# ============================================================================


def _safe_parse(raw: Any) -> dict | None:
    """Parse a tool result that may be a JSON string or already a dict.

    Returns None on parse failure (resilient — never raises).
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


# ============================================================================
# Individual extractors
# ============================================================================


def extract_service_fields(result: dict, ctx: BookingContextV7) -> None:
    """Extract service data from search_services result. Mutates ctx in place.

    Handles 3 shapes:
    - Shape 1 (resolved_service): set service_id, service_name, etc.
    - Shape 2 (clarification_needed): set pending_clarification, candidate_services
    - Shape 3 (services list): set candidate_services
      If exactly 1 result, auto-resolve to service fields.

    Also infers service_audience_hint from service name if not already set.
    """
    # ── Guard: skip mutation if services are locked (SLOT_TAKEN retry protection)
    if ctx.services_locked:
        logger.info(
            "extract_service_fields: SKIPPED — services_locked=True "
            "(selected_services=%s)",
            ctx.selected_services,
        )
        return

    # Shape 1: resolved_service — unambiguous single match
    if "resolved_service" in result:
        svc = result["resolved_service"]
        ctx.service_id = str(svc["id"])
        ctx.service_name = svc["name"]
        ctx.service_category = svc.get("category")
        ctx.service_duration_minutes = svc.get("duration_minutes")
        ctx.service_family = svc.get("family")
        # Build selected_services (primary service first)
        if svc["name"] not in ctx.selected_services:
            ctx.selected_services = [svc["name"]] + [
                s for s in ctx.selected_services if s != svc["name"]
            ]
        # Clear disambiguation state
        ctx.pending_clarification = None
        ctx.candidate_services = []
        # Infer audience hint if not already set
        if not ctx.service_audience_hint:
            ctx.service_audience_hint = extract_service_audience_hint(svc.get("name"))
        # Extract combo recommendations if present and not yet loaded
        combo_recs = svc.get("combo_recommendations", [])
        if combo_recs and not ctx.pending_recommendations:
            ctx.pending_recommendations = [str(r) for r in combo_recs if str(r).strip()]
            ctx.recommendations_shown = False
            logger.info(
                "extract_service_fields: %d combo recommendations loaded",
                len(ctx.pending_recommendations),
            )
        logger.info(
            "extract_service_fields: resolved service '%s' (id=%s)",
            svc.get("name"),
            svc.get("id"),
        )
        return

    # Shape 2: clarification_needed — ambiguous, needs user input
    if "clarification_needed" in result:
        clarification = result["clarification_needed"]
        # Guard: don't overwrite if we already have services selected and this
        # clarification can be auto-resolved by resolve_pending_clarification.
        # This prevents a same-turn search_services pair (one resolved, one
        # needing clarification) from clobbering the resolved service's state.
        if ctx.selected_services and clarification.get("axis") == "audience" and ctx.service_audience_hint:
            # Check if any option matches the existing hint — if so, skip
            hint_lower = _normalize_text(ctx.service_audience_hint)
            options = clarification.get("options", [])
            for opt in options:
                val = _normalize_text(opt.get("value"))
                if hint_lower in val or val in hint_lower:
                    # Auto-resolve inline instead of deferring
                    svc_name = opt["service_name"]
                    if svc_name not in ctx.selected_services:
                        ctx.selected_services = [svc_name] + [
                            s for s in ctx.selected_services if s != svc_name
                        ]
                    logger.info(
                        "extract_service_fields: auto-resolved clarification "
                        "for '%s' (audience hint '%s' matched)",
                        svc_name,
                        ctx.service_audience_hint,
                    )
                    return
        ctx.pending_clarification = clarification
        logger.info(
            "extract_service_fields: clarification needed (axis=%s)",
            clarification.get("axis"),
        )
        return

    # Shape 3: services list — ranked fuzzy matches
    services = result.get("services")
    if services and isinstance(services, list):
        if len(services) == 1:
            # Auto-resolve single result
            svc = services[0]
            ctx.service_id = str(svc["id"])
            ctx.service_name = svc["name"]
            ctx.service_category = svc.get("category")
            ctx.service_duration_minutes = svc.get("duration_minutes")
            if svc["name"] not in ctx.selected_services:
                ctx.selected_services = [svc["name"]] + [
                    s for s in ctx.selected_services if s != svc["name"]
                ]
            ctx.pending_clarification = None
            ctx.candidate_services = []
            if not ctx.service_audience_hint:
                ctx.service_audience_hint = extract_service_audience_hint(svc.get("name"))
            logger.info(
                "extract_service_fields: auto-resolved single candidate '%s'",
                svc.get("name"),
            )
        else:
            ctx.candidate_services = services
            logger.info(
                "extract_service_fields: %d candidates, awaiting user choice",
                len(services),
            )


def extract_slot_fields(result: dict, ctx: BookingContextV7) -> None:
    """Extract slot data from check_availability or find_next_available result.

    Sets offered_slots from the result. Does NOT set selected_slot —
    that requires explicit user choice (the LLM will pass it to book()).

    For find_next_available, extracts from both legacy (available_stylists)
    and v4.2 (selected_stylist_slots, soonest_any) shapes.
    """
    # check_availability shape: {"available_slots": [...]}
    slots = result.get("available_slots")

    # find_next_available shape: flattened from available_stylists
    if not slots:
        available_stylists = result.get("available_stylists", [])
        if available_stylists:
            slots = []
            for stylist_data in available_stylists:
                for slot in stylist_data.get("slots", []):
                    slots.append(slot)

    # find_next_available v4.2: selected_stylist_slots
    selected_stylist_slots = result.get("selected_stylist_slots")
    if selected_stylist_slots and not slots:
        slots = selected_stylist_slots

    if slots:
        # Guard: skip overwrite if the user already has slots displayed and hasn't
        # asked for new availability. This prevents a spurious check_availability
        # call (e.g. during name collection) from replacing the slots the user
        # already chose from, which would make slot_index resolve to the wrong slot.
        if ctx.offered_slots:
            logger.warning(
                "extract_slot_fields: offered_slots already set (%d slots), "
                "skipping overwrite with %d new slots. "
                "Clear offered_slots first to refresh.",
                len(ctx.offered_slots),
                len(slots),
            )
            return
        ctx.offered_slots = slots
        ctx.book_failure_count = 0  # Reset failure counter on new availability
        logger.info("extract_slot_fields: %d slots offered, book_failure_count reset", len(slots))

        # If ALL slots come from the same stylist, auto-set stylist_id/name
        stylist_ids = {s.get("stylist_id") for s in slots if s.get("stylist_id")}
        if len(stylist_ids) == 1:
            sid = stylist_ids.pop()
            ctx.stylist_id = sid
            stylist_name = next(
                (s.get("stylist_name") or s.get("stylist") for s in slots if s.get("stylist_id")),
                None,
            )
            if stylist_name:
                ctx.stylist_name = stylist_name
            logger.info(
                "extract_slot_fields: auto-set stylist_id=%s, name=%s",
                sid,
                stylist_name,
            )

    # find_next_available v4.2: soonest_any
    soonest_any = result.get("soonest_any")
    if soonest_any and isinstance(soonest_any, dict):
        stylist_name = soonest_any.get("stylist_name") or soonest_any.get("stylist", "")
        date_str = soonest_any.get("date", "")
        time_str = soonest_any.get("time", "")
        ctx.soonest_any_slot = f"{date_str} a las {time_str} con {stylist_name}"
        logger.info("extract_slot_fields: soonest_any = %s", ctx.soonest_any_slot)


def extract_stylist_fields(result: dict, ctx: BookingContextV7) -> None:
    """Extract stylist data from list_stylists result.

    Updates prefetched_stylists list. Does NOT auto-assign stylist_id —
    the LLM presents options and the user chooses.
    """
    stylists = result.get("stylists", [])
    if stylists:
        ctx.prefetched_stylists = stylists
        logger.info("extract_stylist_fields: %d stylists loaded", len(stylists))


def extract_customer_fields(result: dict, ctx: BookingContextV7) -> None:
    """Extract customer data from manage_customer result.

    Sets customer_id and customer_name from the response.
    Handles all 3 manage_customer actions (get, create, update).
    """
    # All success shapes include "id" for the customer UUID
    customer_id = result.get("id") or result.get("customer_id")
    if customer_id:
        ctx.customer_id = str(customer_id)

    first_name = result.get("first_name")
    if first_name:
        ctx.customer_name = first_name

    if customer_id or first_name:
        # Reset book failure counter — user provided new data, so prior
        # DATA errors (missing customer_id) are now potentially resolved.
        ctx.book_failure_count = 0
        logger.info(
            "extract_customer_fields: customer_id=%s, name=%s (book_failure_count reset)",
            customer_id,
            first_name,
        )


def extract_booking_result(result: dict, ctx: BookingContextV7) -> None:
    """Extract booking confirmation from book() result.

    Sets _booking_completed flag on success. On failure, the LLM
    sees the error in tool output and handles it conversationally.
    """
    if result.get("success"):
        ctx._booking_completed = True
        ctx.book_failure_count = 0
        ctx.offered_slots = None  # Clear stale slots after successful booking
        ctx.selected_slot = None  # Clear selected slot
        # Capture stylist_id from booking result if present
        booked_stylist = result.get("stylist_id")
        if booked_stylist:
            ctx.stylist_id = str(booked_stylist)
        logger.info(
            "extract_booking_result: booking succeeded (appointment_id=%s)",
            result.get("appointment_id"),
        )
    else:
        ctx.book_failure_count = getattr(ctx, "book_failure_count", 0) + 1
        error_code = result.get("error_code", "")
        if error_code == "SLOT_TAKEN":
            ctx.offered_slots = None  # Force refresh on next availability check
            ctx.selected_slot = None  # Clear stale selection
            logger.info(
                "extract_booking_result: SLOT_TAKEN — cleared offered_slots for refresh"
            )
        logger.info(
            "extract_booking_result: booking failed (error_code=%s, failure_count=%d)",
            result.get("error_code"),
            ctx.book_failure_count,
        )


# ============================================================================
# Dispatcher
# ============================================================================

TOOL_EXTRACTORS: dict[str, Any] = {
    "search_services": extract_service_fields,
    "check_availability": extract_slot_fields,
    "find_next_available": extract_slot_fields,
    "list_stylists": extract_stylist_fields,
    "manage_customer": extract_customer_fields,
    "book": extract_booking_result,
}


def apply_all_tool_results(tool_results: dict[str, Any], ctx: BookingContextV7) -> None:
    """Apply all tool results from an agentic loop iteration to context.

    Routes each tool name to its extractor function. Unknown tools and
    parse failures are silently skipped with a warning log.

    Args:
        tool_results: Dict mapping tool name → list of raw results (str or dict),
            or a single raw result for backwards compatibility.
        ctx: BookingContextV7 to mutate in place.
    """
    for tool_name, raw_results in tool_results.items():
        extractor = TOOL_EXTRACTORS.get(tool_name)
        if extractor is None:
            logger.debug("apply_all_tool_results: no extractor for tool '%s'", tool_name)
            continue

        # Normalize to list for uniform handling (backwards compat with non-list values)
        if not isinstance(raw_results, list):
            raw_results = [raw_results]

        for raw_result in raw_results:
            parsed = _safe_parse(raw_result)
            if parsed is None:
                logger.warning(
                    "apply_all_tool_results: failed to parse result for tool '%s'",
                    tool_name,
                )
                continue

            try:
                extractor(parsed, ctx)
            except Exception:
                logger.exception(
                    "apply_all_tool_results: extractor crashed for tool '%s'",
                    tool_name,
                )

    # ── Post-extraction lock: freeze services once we've moved past service
    # selection into slot selection.  Before offered_slots exist the user may
    # still add add-on services, so we don't lock yet.  Once slots have been
    # offered we lock to prevent a SLOT_TAKEN retry from overwriting services.
    if not ctx.services_locked and ctx.selected_services and ctx.offered_slots:
        ctx.services_locked = True
        logger.info(
            "apply_all_tool_results: services_locked=True "
            "(selected_services=%s, offered_slots present)",
            ctx.selected_services,
        )
