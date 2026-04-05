"""
Tool Result Extractors for BookingMode.

Pure functions that extract canonical fields from tool responses into
BookingContext. They do NOT make flow decisions — that's the LLM's job.

Each extractor:
- Receives a parsed dict (tool result) and a BookingContext
- Mutates the context in place
- Never raises — fails silently with logging

Deleted (compensatory code, no longer needed):
- _resolve_user_candidate_selection   — LLM handles candidate choice via conversation
- _resolve_user_clarification_selection — LLM handles clarification choice
- _previous_assistant_presented_clarification — guard for deleted resolver
- _previous_assistant_presented_candidates   — guard for deleted resolver
- _apply_resolved_option                     — helper for deleted resolvers
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from agent.modes.booking_context import BookingContext
from shared.audience_maps import AUDIENCE_HINT_MAP

logger = logging.getLogger(__name__)

# ============================================================================
# Utilities
# ============================================================================


def _normalize_text(value: str | None) -> str:
    """Unicode NFKD normalization, lowercase, strip accents."""
    raw = (value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def extract_service_audience_hint(value: str | None) -> str | None:
    """Extract audience hint from a service name string.

    Scans the normalized text for known audience tokens and returns the
    corresponding hint (e.g. "adult_male", "adult_female").
    Used by extract_service_fields to auto-resolve audience clarifications.
    """
    normalized = _normalize_text(value)
    if not normalized:
        return None
    for token, hint in AUDIENCE_HINT_MAP.items():
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            return hint
    return None


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


def _upsert_service_detail(ctx: BookingContext, svc: dict) -> None:
    """Add or update a service's detail entry in selected_services_details.

    Deduplicates by name. Only stores entries where description is non-null.
    Caps list at 5 entries to prevent context overflow.
    """
    desc = svc.get("description")
    if not desc:
        return
    name = svc.get("name", "")
    duration = svc.get("duration_minutes")
    # Remove existing entry for same service (upsert)
    ctx.selected_services_details = [
        d for d in ctx.selected_services_details if d.get("name") != name
    ]
    if len(ctx.selected_services_details) < 5:
        ctx.selected_services_details.append(
            {"name": name, "duration": duration, "description": desc}
        )


def _update_combined_duration(ctx: BookingContext, new_svc: dict) -> None:
    """Recalculate service_duration_minutes as the sum of all selected services.

    Called after ADDITIVE append. Uses selected_services_details for known
    durations, plus the incoming service's duration_minutes.
    """
    total = 0
    seen_names: set[str] = set()
    for detail in ctx.selected_services_details:
        dur = detail.get("duration_minutes") or detail.get("duration") or 0
        name = detail.get("name", "")
        if dur and name:
            total += dur
            seen_names.add(name)
    # Add incoming service if not already counted via details
    new_name = new_svc.get("name", "")
    if new_name not in seen_names:
        new_dur = new_svc.get("duration_minutes") or 0
        total += new_dur
    # Add primary service if not in details
    if ctx.service_duration_minutes and ctx.service_name and ctx.service_name not in seen_names:
        total += ctx.service_duration_minutes
    if total > 0:
        ctx.service_duration_minutes = total


def _clear_date_metadata(ctx: BookingContext) -> None:
    """No-op — date substitution metadata fields were removed in the 20-field rewrite.

    Kept as a stub so existing call sites in extract_slot_fields don't need changing.
    """
    pass


# ============================================================================
# Individual extractors
# ============================================================================


def extract_service_fields(result: dict, ctx: BookingContext) -> None:
    """Extract service data from search_services result. Mutates ctx in place.

    Handles 3 shapes:
    - Shape 1 (resolved_service): set service_id, service_name, etc.
    - Shape 2 (clarification_needed): append to pending_clarifications, set candidate_services
    - Shape 3 (services list): set candidate_services
      If exactly 1 result, auto-resolve to service fields.

    Also infers audience hint from service name for auto-resolving clarifications.
    """
    # ── Guard: when locked, protect scalar fields but allow appending to selected_services
    if ctx.services_locked:
        svc = result.get("resolved_service") or (
            result.get("services", [None])[0]
            if isinstance(result.get("services"), list) and len(result.get("services", [])) == 1
            else None
        )
        if svc and svc.get("name") and svc["name"] not in ctx.selected_services:
            ctx.selected_services.append(svc["name"])
            _upsert_service_detail(ctx, svc)
            logger.info(
                "extract_service_fields: services_locked but APPENDED '%s' (selected_services=%s)",
                svc["name"],
                ctx.selected_services,
            )
        else:
            logger.info(
                "extract_service_fields: services_locked, no new service to append "
                "(selected_services=%s)",
                ctx.selected_services,
            )
        return

    # Shape 1: resolved_service — unambiguous single match
    if "resolved_service" in result:
        svc = result["resolved_service"]

        # ── ADDITIVE MODE: second+ service in same agentic round ──────────
        # When primary service already resolved AND not locked AND incoming ID
        # differs, APPEND to selected_services without overwriting scalar fields.
        if ctx.service_id and not ctx.services_locked and str(svc.get("id", "")) != ctx.service_id:
            if svc["name"] not in ctx.selected_services:
                ctx.selected_services.append(svc["name"])
                _upsert_service_detail(ctx, svc)
            # Update combined duration: sum all known durations
            _update_combined_duration(ctx, svc)
            logger.info(
                "extract_service_fields: ADDITIVE — appended '%s' (primary='%s', combined=%d min)",
                svc["name"],
                ctx.service_name,
                ctx.service_duration_minutes or 0,
            )
            return

        # ── PRIMARY PATH ──────────────────────────────────────────────────
        ctx.service_id = str(svc["id"])
        ctx.service_name = svc["name"]
        ctx.service_category = svc.get("category")
        ctx.service_duration_minutes = svc.get("duration_minutes")
        # Build selected_services (primary service first)
        if svc["name"] not in ctx.selected_services:
            ctx.selected_services = [svc["name"]] + [
                s for s in ctx.selected_services if s != svc["name"]
            ]
        # Clear disambiguation: remove only clarification entries whose options
        # include the resolved service (preserve unrelated clarifications)
        resolved_name = svc["name"]
        ctx.pending_clarifications = [
            pc
            for pc in ctx.pending_clarifications
            if not any(opt.get("service_name") == resolved_name for opt in pc.get("options", []))
        ]
        ctx.candidate_services = []
        # Extract service description for transparency
        _upsert_service_detail(ctx, svc)
        # Track resolved disambiguation axes so they're never re-asked
        resolved_axes = result.get("resolved_axes")
        if resolved_axes and isinstance(resolved_axes, dict):
            ctx.resolved_axes.update(resolved_axes)
            logger.info(
                "extract_service_fields: stored resolved_axes=%s",
                resolved_axes,
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
        # Guard: if service name implies an audience, auto-resolve inline
        # using the audience hint extracted from the service name context.
        # The LLM will ask naturally in the next turn if still ambiguous.
        if clarification.get("axis") == "audience":
            # Check if any option's service name gives us an audience hint
            options = clarification.get("options", [])
            # Look for audience hint in the first option's service_name
            for opt in options:
                hint = extract_service_audience_hint(opt.get("service_name", ""))
                if hint:
                    # We found a hint — queue the clarification for the LLM to ask
                    break

        # Axis+service_key upsert: replace existing entry for same (axis, service_key)
        # pair instead of same axis alone. This preserves clarifications for two
        # different services that share the same axis (e.g., both need "audience").
        axis = clarification.get("axis")
        service_key = clarification.get("service_key", "")
        ctx.pending_clarifications = [
            pc
            for pc in ctx.pending_clarifications
            if not (pc.get("axis") == axis and pc.get("service_key", "") == service_key)
        ]
        ctx.pending_clarifications.append(clarification)
        logger.info(
            "extract_service_fields: clarification upserted (axis=%s, service_key=%r, queue_size=%d)",
            axis,
            service_key,
            len(ctx.pending_clarifications),
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
            # Remove only matching clarification entries (preserve unrelated)
            resolved_name = svc["name"]
            ctx.pending_clarifications = [
                pc
                for pc in ctx.pending_clarifications
                if not any(
                    opt.get("service_name") == resolved_name for opt in pc.get("options", [])
                )
            ]
            ctx.candidate_services = []
            _upsert_service_detail(ctx, svc)
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


def extract_slot_fields(result: dict, ctx: BookingContext) -> None:
    """Extract slot data from check_availability or find_next_available result.

    Sets offered_slots from the result. Does NOT set selected_slot —
    that requires explicit user choice (the LLM will pass it to book()).

    For find_next_available, extracts from both legacy (available_stylists)
    and v4.2 (selected_stylist_slots, soonest_any) shapes.
    """
    # Clear stale date metadata (no-op in new 20-field context)
    _clear_date_metadata(ctx)

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
        # Normalize day_name → day_label for consistent rendering
        # Availability tools return "day_name" but dynamic context reads "day_label"
        for slot in slots:
            if "day_label" not in slot and "day_name" in slot:
                date_str = slot.get("date", "")
                day_name = slot["day_name"].capitalize()
                if date_str:
                    try:
                        day_num = date_str.split("-")[2].lstrip("0")
                        month_names = [
                            "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
                            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
                        ]
                        month_num = int(date_str.split("-")[1])
                        month_name = month_names[month_num]
                        slot["day_label"] = f"{day_name} {day_num} de {month_name}"
                    except (IndexError, ValueError):
                        slot["day_label"] = day_name
                else:
                    slot["day_label"] = day_name

        ctx.offered_slots = slots
        logger.info("extract_slot_fields: %d slots offered", len(slots))

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
    else:
        # No slots returned — clear offered_slots to prevent stale slots from persisting
        ctx.offered_slots = []
        logger.info("extract_slot_fields: tool returned no slots, clearing offered_slots")


def extract_stylist_fields(result: dict, ctx: BookingContext) -> None:
    """Extract stylist data from list_stylists result.

    Updates prefetched_stylists list. Does NOT auto-assign stylist_id —
    the LLM presents options and the user chooses.
    """
    stylists = result.get("stylists", [])
    if stylists:
        ctx.prefetched_stylists = stylists
        logger.info("extract_stylist_fields: %d stylists loaded", len(stylists))


def extract_query_info_fields(result: dict, ctx: BookingContext) -> None:
    """No-op extractor for query_info tool results.

    GAP-03: query_info is an informational tool (FAQs, hours, location).
    Its results do not map to BookingContext fields — the LLM reads the
    tool output directly and crafts a response. This extractor exists so
    that apply_all_tool_results() doesn't log 'no extractor for query_info'
    as an unregistered tool and silently drops the result.
    """
    logger.debug(
        "extract_query_info_fields: query_info result is informational — no ctx fields updated"
    )


def extract_customer_fields(result: dict, ctx: BookingContext) -> None:
    """Extract customer data from manage_customer result.

    Sets customer_id and customer_name from the response.
    Handles all 3 manage_customer actions (get, create, update).
    """
    # Detect error responses (all failures return {"error": ...})
    if result.get("error"):
        logger.warning(
            "extract_customer_fields: manage_customer error: %s",
            result.get("error"),
        )
        return

    # Detect "customer not found" responses from action='get'.
    # This is a VALID response (new customer), NOT a failure.
    # The LLM sees "exists: False" in the tool output and knows to call action='create'.
    if result.get("exists") is False:
        logger.info(
            "extract_customer_fields: customer not found (exists=False) — valid response, "
            "LLM should call action='create' next"
        )
        return

    # All success shapes include "id" for the customer UUID
    customer_id = result.get("id") or result.get("customer_id")
    if customer_id:
        ctx.customer_id = str(customer_id)

    first_name = result.get("first_name")
    last_name = result.get("last_name")
    if first_name:
        # Combine first + last name for display
        if last_name and last_name.strip():
            ctx.customer_name = f"{first_name} {last_name.strip()}"
        else:
            ctx.customer_name = first_name

    if customer_id or first_name:
        logger.info(
            "extract_customer_fields: customer_id=%s, name=%s",
            customer_id,
            ctx.customer_name,
        )


def extract_booking_result(result: dict, ctx: BookingContext) -> None:
    """Extract booking confirmation from book() result.

    Sets _booking_completed flag on success. On failure, the LLM
    sees the error in tool output and handles it conversationally.

    Rejections (from ToolCallRejection) are a no-op — they don't count as
    a real book() attempt, so no side effects.
    """
    # Early return for rejected tool calls — no side effects
    if result.get("rejected"):
        logger.info(
            "extract_booking_result: skipping rejected book() (error_code=%s)",
            result.get("error_code"),
        )
        return

    # Lock services on FIRST book() attempt (success OR failure).
    # This prevents SLOT_TAKEN retry from clobbering selected_services.
    if not ctx.services_locked:
        ctx.services_locked = True
        logger.info(
            "extract_booking_result: services_locked=True on first book() attempt "
            "(selected_services=%s)",
            ctx.selected_services,
        )

    if result.get("success"):
        ctx._booking_completed = True
        ctx.offered_slots = None  # Clear stale slots after successful booking
        ctx.selected_slot = None  # Clear selected slot
        # Clear all transient booking fields so context is clean for a follow-up booking
        ctx.reset_transient()
        logger.info(
            "extract_booking_result: booking succeeded (appointment_id=%s), transient fields reset",
            result.get("appointment_id"),
        )
    else:
        error_code = result.get("error_code", "")
        if error_code == "SLOT_TAKEN":
            ctx.offered_slots = None  # Force refresh on next availability check
            ctx.selected_slot = None  # Clear stale selection
            logger.info("extract_booking_result: SLOT_TAKEN — cleared offered_slots for refresh")
        logger.info(
            "extract_booking_result: booking failed (error_code=%s)",
            result.get("error_code"),
        )


# ============================================================================
# Dispatcher
# ============================================================================


def extract_create_hold_result(result: dict, ctx: BookingContext) -> None:
    """Extract create_hold() result into BookingContext.

    On success: stores hold_id in ctx.hold_id.
    On SLOT_UNAVAILABLE: clears slot state.
    Other errors: logged, no state mutation.
    """
    status = result.get("status")
    if status == "ok":
        ctx.hold_id = result.get("hold_id")
        logger.info("extract_create_hold_result: HOLD created — hold_id=%s", ctx.hold_id)
    elif result.get("error") == "SLOT_UNAVAILABLE":
        ctx.offered_slots = None
        ctx.selected_slot = None
        ctx.hold_id = None
        logger.info("extract_create_hold_result: SLOT_UNAVAILABLE — cleared slot state")
    else:
        logger.warning(
            "extract_create_hold_result: unexpected error — %s: %s",
            result.get("error"),
            result.get("message"),
        )


def extract_confirm_from_hold_result(result: dict, ctx: BookingContext) -> None:
    """Extract confirm_from_hold() result into BookingContext.

    On success: marks booking as completed (delegates to same flag as book()).
    On HOLD_EXPIRED: clears hold_id and slot, triggers availability refresh.
    On HOLD_INVALID_STATE / HOLD_NOT_FOUND: logs warning, no state mutation.
    """
    status = result.get("status")
    if status == "ok":
        ctx._booking_completed = True
        ctx.hold_id = None
        ctx.offered_slots = None
        ctx.selected_slot = None
        ctx.reset_transient()
        logger.info(
            "extract_confirm_from_hold_result: booking confirmed via hold (appointment_id=%s)",
            result.get("appointment_id"),
        )
    elif result.get("error") == "HOLD_EXPIRED":
        ctx.hold_id = None
        ctx.offered_slots = None
        ctx.selected_slot = None
        logger.warning("extract_confirm_from_hold_result: HOLD_EXPIRED — cleared hold/slot")
    elif result.get("error") in ("HOLD_INVALID_STATE", "HOLD_NOT_FOUND"):
        logger.warning(
            "extract_confirm_from_hold_result: error=%s — %s",
            result.get("error"),
            result.get("message"),
        )
    else:
        logger.warning(
            "extract_confirm_from_hold_result: unexpected result — %s",
            result,
        )


TOOL_EXTRACTORS: dict[str, Any] = {
    "search_services": extract_service_fields,
    "check_availability": extract_slot_fields,
    "find_next_available": extract_slot_fields,
    "list_stylists": extract_stylist_fields,
    "manage_customer": extract_customer_fields,
    "book": extract_booking_result,
    "create_hold": extract_create_hold_result,
    "confirm_from_hold": extract_confirm_from_hold_result,
    # GAP-03: query_info is informational — no-op extractor prevents log noise
    # and provides a hook for future field extraction if needed.
    "query_info": extract_query_info_fields,
}


def apply_all_tool_results(tool_results: dict[str, Any], ctx: BookingContext) -> None:
    """Apply all tool results from an agentic loop iteration to context.

    Routes each tool name to its extractor function. Unknown tools and
    parse failures are silently skipped with a warning log.

    Args:
        tool_results: Dict mapping tool name → list of raw results (str or dict),
            or a single raw result for backwards compatibility.
        ctx: BookingContext to mutate in place.
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
