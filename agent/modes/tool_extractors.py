"""
Tool Result Extractors for BookingMode.

Pure functions that extract canonical fields from tool responses into
BookingContext. They do NOT make flow decisions — that's the LLM's job.

Each extractor:
- Receives a parsed dict (tool result) and a BookingContext
- Mutates the context in place
- Never raises — fails silently with logging
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
# Axis hint maps (audience, hair_density, hair_length)
# ============================================================================

# AUDIENCE_HINT_MAP is imported from shared.audience_maps (single source of truth)


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

    for token, hint in AUDIENCE_HINT_MAP.items():
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            return hint

    return None


def _apply_resolved_option(ctx: BookingContext, opt: dict, axis: str, resolved_value: str) -> None:
    """Apply a resolved clarification option to the booking context."""
    ctx.service_id = str(opt["service_id"])
    ctx.service_name = opt["service_name"]
    ctx.service_category = opt.get("category")
    ctx.service_duration_minutes = opt.get("duration_minutes")
    ctx.service_family = opt.get("family")
    # APPEND, not overwrite (same pattern as Shape 1)
    if opt["service_name"] not in ctx.selected_services:
        ctx.selected_services = [opt["service_name"]] + [
            s for s in ctx.selected_services if s != opt["service_name"]
        ]
    ctx.candidate_services = []
    # Copy rich metadata (combo_recommendations + description) — same pattern as Shape 1 (REQ-1)
    recommendations = opt.get("combo_recommendations") or []
    if recommendations and not ctx.pending_recommendations:
        ctx.pending_recommendations = list(recommendations)
        ctx.recommendations_shown = False
    description = opt.get("description")
    if description:
        _upsert_service_detail(
            ctx,
            {
                "name": opt.get("service_name", ""),
                "description": description,
                "duration_minutes": opt.get("duration_minutes"),
            },
        )
    logger.info(
        "resolve_pending_clarification: auto-resolved '%s' "
        "via axis '%s'='%s' (remaining_pending=%d)",
        opt["service_name"],
        axis,
        resolved_value,
        len(ctx.pending_clarifications),
    )


def _previous_assistant_presented_clarification(messages: list[dict]) -> bool:
    """Check if the most recent assistant message presented a numbered clarification list.

    Iterates ``messages`` in reverse, finds the first (most recent)
    ``role == "assistant"`` message, and returns True if its content matches
    the numbered-list pattern ``r'^\\d+\\.\\s'`` in multiline mode.

    Returns False if no assistant message is found or the last one has no numbered list.
    """
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content") or ""
            return bool(re.search(r"^\d+\.\s", content, re.MULTILINE))
    return False


def _resolve_user_clarification_selection(
    user_message: str,
    ctx: BookingContext,
    messages: list[dict] | None = None,
) -> bool:
    """Resolve a clarification selection from the user message.

    Deterministically matches the user's reply (number or label text) against
    the stored options in ``ctx.pending_clarifications[0]`` and calls
    ``_apply_resolved_option()`` on success.  Must NOT call any tools or LLM —
    purely synchronous Python.

    Guards (returns False immediately if ANY fail):
    - ``ctx.pending_clarifications`` is empty
    - ``ctx.service_id`` is already set (prevent overwrite)
    - ``messages`` provided and last assistant did NOT present a numbered list

    Match logic (priority order):
    1. Bare number: ``r'^\\s*(\\d+)\\s*$'`` → ``options[n-1]``
    2. Number embedded in text: ``r'\\b(\\d+)\\b'`` → ``options[n-1]``
    3. Label/value text: normalized substring containment

    On success: calls ``_apply_resolved_option()``, removes matched entry from
    ``ctx.pending_clarifications``, returns True.
    On no match: returns False (LLM handles it normally).
    """
    # Guard: nothing to resolve
    if not ctx.pending_clarifications:
        return False

    # Guard: service already resolved — don't overwrite
    if ctx.service_id is not None:
        return False

    # Guard: only resolve if assistant actually presented a clarification list
    if messages is not None and not _previous_assistant_presented_clarification(messages):
        return False

    # Work on the first pending entry (FIFO)
    entry = ctx.pending_clarifications[0]
    options: list[dict] = entry.get("options", [])
    axis: str = entry.get("axis", "")

    if not options:
        return False

    matched_opt: dict | None = None
    resolved_value: str = ""

    # Priority 1: bare number  e.g. "4"
    bare_match = re.match(r"^\s*(\d+)\s*$", user_message)
    if bare_match:
        idx = int(bare_match.group(1)) - 1
        if 0 <= idx < len(options):
            matched_opt = options[idx]
            resolved_value = str(idx + 1)

    # Priority 2: number embedded in text  e.g. "el 2 por favor"
    if matched_opt is None:
        embedded_match = re.search(r"\b(\d+)\b", user_message)
        if embedded_match:
            idx = int(embedded_match.group(1)) - 1
            if 0 <= idx < len(options):
                matched_opt = options[idx]
                resolved_value = str(idx + 1)

    # Priority 3: label / value substring match (normalized)
    if matched_opt is None:
        user_norm = _normalize_text(user_message)
        for opt in options:
            label_norm = _normalize_text(opt.get("label"))
            value_norm = _normalize_text(opt.get("value"))
            if (label_norm and (label_norm in user_norm or user_norm in label_norm)) or (
                value_norm and (value_norm in user_norm or user_norm in value_norm)
            ):
                matched_opt = opt
                resolved_value = opt.get("value", opt.get("label", ""))
                break

    if matched_opt is None:
        return False

    # Apply and remove resolved entry
    _apply_resolved_option(ctx, matched_opt, axis, resolved_value)
    ctx.pending_clarifications = [e for e in ctx.pending_clarifications if e is not entry]
    return True


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


def extract_service_fields(result: dict, ctx: BookingContext) -> None:
    """Extract service data from search_services result. Mutates ctx in place.

    Handles 3 shapes:
    - Shape 1 (resolved_service): set service_id, service_name, etc.
    - Shape 2 (clarification_needed): append to pending_clarifications, set candidate_services
    - Shape 3 (services list): set candidate_services
      If exactly 1 result, auto-resolve to service fields.

    Also infers service_audience_hint from service name if not already set.
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
        # Clear disambiguation: remove only clarification entries whose options
        # include the resolved service (preserve unrelated clarifications)
        resolved_name = svc["name"]
        ctx.pending_clarifications = [
            pc
            for pc in ctx.pending_clarifications
            if not any(opt.get("service_name") == resolved_name for opt in pc.get("options", []))
        ]
        ctx.candidate_services = []
        # Infer audience hint if not already set
        if not ctx.service_audience_hint:
            ctx.service_audience_hint = extract_service_audience_hint(svc.get("name"))
        # Path C: metadata propagated here (see REQ-3)
        # Extract combo recommendations if present and not yet loaded
        combo_recs = svc.get("combo_recommendations", [])
        if combo_recs and not ctx.pending_recommendations:
            ctx.pending_recommendations = [str(r) for r in combo_recs if str(r).strip()]
            ctx.recommendations_shown = False
            logger.info(
                "extract_service_fields: %d combo recommendations loaded",
                len(ctx.pending_recommendations),
            )
        # Extract service description for transparency
        _upsert_service_detail(ctx, svc)
        logger.info(
            "extract_service_fields: resolved service '%s' (id=%s)",
            svc.get("name"),
            svc.get("id"),
        )
        return

    # Shape 2: clarification_needed — ambiguous, needs user input
    if "clarification_needed" in result:
        clarification = result["clarification_needed"]
        # Guard: if we have an audience hint that matches, auto-resolve inline
        # instead of queueing (prevents unnecessary disambiguation prompts).
        if clarification.get("axis") == "audience" and ctx.service_audience_hint:
            hint_lower = _normalize_text(ctx.service_audience_hint)
            options = clarification.get("options", [])
            for opt in options:
                val = _normalize_text(opt.get("value"))
                if hint_lower in val or val in hint_lower:
                    # Delegate to _apply_resolved_option — sets ALL 5 canonical fields
                    # (service_id, service_name, service_category, service_duration_minutes,
                    # service_family) plus selected_services, recommendations, description.
                    _apply_resolved_option(ctx, opt, "audience", ctx.service_audience_hint)
                    logger.info(
                        "extract_service_fields: auto-resolved clarification "
                        "for '%s' (audience hint '%s' matched)",
                        opt["service_name"],
                        ctx.service_audience_hint,
                    )
                    return
        # Axis-based upsert: replace existing entry for same axis instead of
        # blindly appending (prevents duplicate clarification entries for the
        # same axis when the LLM retries a failed clarification question).
        axis = clarification.get("axis")
        ctx.pending_clarifications = [
            pc for pc in ctx.pending_clarifications if pc.get("axis") != axis
        ]
        ctx.pending_clarifications.append(clarification)
        logger.info(
            "extract_service_fields: clarification upserted (axis=%s, queue_size=%d)",
            axis,
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
            if not ctx.service_audience_hint:
                ctx.service_audience_hint = extract_service_audience_hint(svc.get("name"))
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


def _clear_date_metadata(ctx: BookingContext) -> None:
    """Reset date substitution metadata before a new availability search."""
    ctx.date_parse_error = False
    ctx.substitution_made = False
    ctx.substitution_reason = None
    ctx.date_requested = None
    ctx.date_substituted = None
    ctx.min_valid_date = None


def extract_slot_fields(result: dict, ctx: BookingContext) -> None:
    """Extract slot data from check_availability or find_next_available result.

    Sets offered_slots from the result. Does NOT set selected_slot —
    that requires explicit user choice (the LLM will pass it to book()).

    For find_next_available, extracts from both legacy (available_stylists)
    and v4.2 (selected_stylist_slots, soonest_any) shapes.
    """
    # Clear stale date metadata at the start of each new availability extraction
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
        ctx.offered_slots = slots
        ctx.book_failure_count = 0  # Reset failure counter on new availability
        ctx.needs_availability_refresh = False  # Fresh availability clears SLOT_TAKEN block
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
    else:
        # No slots returned — clear offered_slots to prevent stale slots from persisting
        ctx.offered_slots = []
        logger.info("extract_slot_fields: tool returned no slots, clearing offered_slots")

    # find_next_available v4.2: soonest_any
    soonest_any = result.get("soonest_any")
    if soonest_any and isinstance(soonest_any, dict):
        stylist_name = soonest_any.get("stylist_name") or soonest_any.get("stylist", "")
        date_str = soonest_any.get("date", "")
        time_str = soonest_any.get("time", "")
        ctx.soonest_any_slot = f"{date_str} a las {time_str} con {stylist_name}"
        logger.info("extract_slot_fields: soonest_any = %s", ctx.soonest_any_slot)

    # Propagate date substitution / parse-error metadata from tool result to context
    ctx.substitution_made = result.get("substitution_made", False)
    ctx.substitution_reason = result.get("substitution_reason")
    ctx.date_requested = result.get("date_requested")
    ctx.date_substituted = result.get("date_substituted")
    ctx.min_valid_date = result.get("min_valid_date")
    ctx.date_parse_error = result.get("date_parse_error", False)
    if ctx.substitution_made or ctx.date_parse_error:
        logger.info(
            "extract_slot_fields: date metadata — substitution_made=%s, date_parse_error=%s, "
            "date_requested=%s, date_substituted=%s",
            ctx.substitution_made,
            ctx.date_parse_error,
            ctx.date_requested,
            ctx.date_substituted,
        )


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

    If future requirements need to extract booking-relevant data from
    query_info (e.g. parsed business hours for slot validation), this is
    the right place to add that logic.
    """
    logger.debug(
        "extract_query_info_fields: query_info result is informational — no ctx fields updated"
    )


def extract_customer_fields(result: dict, ctx: BookingContext) -> None:
    """Extract customer data from manage_customer result.

    Sets customer_id and customer_name from the response.
    Handles all 3 manage_customer actions (get, create, update).
    Tracks failures via manage_customer_failure_count for circuit breaker.
    """
    # Detect error responses (all failures return {"error": ...})
    if result.get("error"):
        ctx.manage_customer_failure_count += 1
        logger.warning(
            "extract_customer_fields: manage_customer error (count=%d): %s",
            ctx.manage_customer_failure_count,
            result.get("error"),
        )
        return

    # Detect "customer not found" responses from action='get'.
    # This is a VALID response (new customer), NOT a failure.
    # The LLM sees "exists: False" in the tool output and knows to call action='create'.
    # Do NOT increment the failure counter here — doing so causes the circuit breaker to
    # trip on the normal get→create sequence for new customers (get returns exists=False,
    # then create increments the count to 2, threshold fires and excludes manage_customer).
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
    if first_name:
        ctx.customer_name = first_name

    if customer_id or first_name:
        # Reset failure counters — user provided new data, so prior
        # errors are now potentially resolved.
        ctx.book_failure_count = 0
        ctx.manage_customer_failure_count = 0
        logger.info(
            "extract_customer_fields: customer_id=%s, name=%s (failure counters reset)",
            customer_id,
            first_name,
        )


def extract_booking_result(result: dict, ctx: BookingContext) -> None:
    """Extract booking confirmation from book() result.

    Sets _booking_completed flag on success. On failure, the LLM
    sees the error in tool output and handles it conversationally.

    Rejections (from ToolCallRejection) are a no-op — they don't count as
    a real book() attempt, so no side effects (no services_locked, no
    book_failure_count increment, no needs_availability_refresh change).
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
        ctx.book_failure_count = 0
        ctx.offered_slots = None  # Clear stale slots after successful booking
        ctx.last_booked_slot = ctx.selected_slot  # Snapshot before clearing for F-8
        ctx.selected_slot = None  # Clear selected slot
        # Capture all confirmed service names BEFORE reset_transient() clears draft fields.
        # confirmed_services is excluded from reset_transient() so it survives the reset.
        # REQ-4: priority chain for confirmed_services
        # 1. Structured list of strings (most reliable)
        services_list = result.get("services", [])
        if (
            services_list
            and isinstance(services_list, list)
            and all(isinstance(s, str) for s in services_list)
        ):
            ctx.confirmed_services = [s.strip() for s in services_list if s.strip()]
        # 2. service_names: list or comma-separated string fallback
        elif result.get("service_names"):
            svc_names = result["service_names"]
            if isinstance(svc_names, list) and all(isinstance(s, str) for s in svc_names):
                ctx.confirmed_services = [s.strip() for s in svc_names if s.strip()]
            else:
                try:
                    ctx.confirmed_services = [
                        s.strip() for s in str(svc_names).split(",") if s.strip()
                    ]
                except Exception:
                    ctx.confirmed_services = []
        # 3. Single service_name from result
        elif result.get("service_name"):
            ctx.confirmed_services = [result["service_name"]]
        # 4. Last resort: service_name from context (set before book() was called)
        elif ctx.service_name:
            ctx.confirmed_services = [ctx.service_name]
        else:
            ctx.confirmed_services = []
        # Capture stylist_id from booking result if present
        booked_stylist = result.get("stylist_id")
        if booked_stylist:
            ctx.stylist_id = str(booked_stylist)
        # Clear all transient booking fields so context is clean for a follow-up booking
        ctx.reset_transient()
        logger.info(
            "extract_booking_result: booking succeeded (appointment_id=%s), transient fields reset",
            result.get("appointment_id"),
        )
    else:
        ctx.book_failure_count = getattr(ctx, "book_failure_count", 0) + 1
        error_code = result.get("error_code", "")
        if error_code == "SLOT_TAKEN":
            ctx.offered_slots = None  # Force refresh on next availability check
            ctx.selected_slot = None  # Clear stale selection
            ctx.needs_availability_refresh = True  # Block book() until fresh availability
            logger.info("extract_booking_result: SLOT_TAKEN — cleared offered_slots for refresh")
        logger.info(
            "extract_booking_result: booking failed (error_code=%s, failure_count=%d)",
            result.get("error_code"),
            ctx.book_failure_count,
        )


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

    # Lock removed from here — moved to extract_booking_result().
    # Services can be added until the first book() attempt.
