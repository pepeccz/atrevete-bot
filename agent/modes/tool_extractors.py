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

logger = logging.getLogger(__name__)

# ============================================================================
# Axis hint maps (audience, hair_density, hair_length)
# ============================================================================

_AUDIENCE_HINT_MAP: dict[str, str] = {
    # adult_male
    "caballero": "adult_male",
    "hombre": "adult_male",
    "adulto": "adult_male",
    "senor": "adult_male",
    "chico": "adult_male",
    # adult_female
    "dama": "adult_female",
    "mujer": "adult_female",
    "adulta": "adult_female",
    "senora": "adult_female",
    "chica": "adult_female",
    "seorita": "adult_female",
    "srita": "adult_female",
    # child_male
    "nino": "child_male",
    "nene": "child_male",
    "chiquitin": "child_male",
    # child_female
    "nina": "child_female",
    "nena": "child_female",
    "chiquitina": "child_female",
    # baby
    "bebe": "baby",
}

# Maps Spanish natural language → hair_density axis values used by resolve_candidates()
# Axis values: "normal" | "extra"
_HAIR_DENSITY_HINT_MAP: dict[str, str] = {
    "normal": "normal",
    "medio": "normal",
    "fino": "normal",
    "cabello normal": "normal",
    "pelo normal": "normal",
    "pelo fino": "normal",
    "cabello fino": "normal",
    "cabello medio": "normal",
    "pelo medio": "normal",
    "poco pelo": "normal",
    "grueso": "extra",
    "denso": "extra",
    "espeso": "extra",
    "mucho pelo": "extra",
    "bastante pelo": "extra",
    "pelo grueso": "extra",
    "cabello grueso": "extra",
    "pelo denso": "extra",
    "cabello denso": "extra",
    "pelo espeso": "extra",
    "cabello espeso": "extra",
    "muy largo": "extra",
    "pelo muy largo": "extra",
    "cabello muy largo": "extra",
    "extra grueso": "extra",
}

# Maps Spanish natural language → hair_length axis values used by resolve_candidates()
# Axis values: "short_medium" | "long"
_HAIR_LENGTH_HINT_MAP: dict[str, str] = {
    "corto": "short_medium",
    "medio": "short_medium",
    "por los hombros": "short_medium",
    "pelo corto": "short_medium",
    "pelo medio": "short_medium",
    "cabello corto": "short_medium",
    "cabello medio": "short_medium",
    "corto o medio": "short_medium",
    "largo": "long",
    "muy largo": "long",
    "pelo largo": "long",
    "cabello largo": "long",
    "pelo muy largo": "long",
    "cabello muy largo": "long",
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


def resolve_pending_clarification(ctx: BookingContext, user_message: str = "") -> bool:
    """Attempt to resolve pending clarifications from the queue using axis hint maps.

    Called as a pre-resolver in BookingMode.handle() AFTER _resolve_audience_hint()
    and BEFORE _build_messages(). Iterates ctx.pending_clarifications and attempts
    to match the user's natural-language answer against the appropriate hint map
    for each axis. Handles all 3 axes: audience, hair_density, hair_length.

    Args:
        ctx: The current BookingContext (mutated in place on match).
        user_message: The raw user message from the current turn. Used to match
            ALL axes: audience (fallback when ctx.service_audience_hint is None),
            hair_density, and hair_length via their respective hint maps.

    On a successful match for any axis:
    - Sets service_id, service_name, service_category, service_duration_minutes
    - Appends to selected_services (NOT overwrite)
    - Removes the matched entry from pending_clarifications
    - Clears candidate_services
    Returns True if any resolution happened, False otherwise.

    Axis resolution strategy:
    - audience: derive canonical hint from ctx.service_audience_hint (preferred) OR
      from user_message via _AUDIENCE_HINT_MAP (fallback), then match against option
      values/labels using multiple strategies (canonical value, label substring, token).
    - hair_density: match user_message against _HAIR_DENSITY_HINT_MAP
    - hair_length: match user_message against _HAIR_LENGTH_HINT_MAP
    """
    if not ctx.pending_clarifications:
        return False

    resolved_any = False

    # Normalize user message for hint map matching
    user_text = _normalize_text(user_message)

    # Iterate over a copy so we can safely remove items during iteration
    remaining_clarifications = list(ctx.pending_clarifications)
    still_pending: list[dict] = []

    for clarification in remaining_clarifications:
        axis = clarification.get("axis")

        # ── audience axis: use service_audience_hint OR derive from user_message ──
        if axis == "audience":
            # Derive hint from user_message if not already in context.
            # This handles the common case where the user answers the clarification
            # question with a natural phrase like "dama", "para señora", "soy mujer",
            # but the hint was never persisted from a previous turn.
            audience_hint = ctx.service_audience_hint
            if audience_hint is None and user_text:
                audience_hint = _match_hint_map(user_text, _AUDIENCE_HINT_MAP)
            if audience_hint is None:
                still_pending.append(clarification)
                continue
            hint_lower = _normalize_text(audience_hint)
            options = clarification.get("options", [])
            matched = False
            for opt in options:
                opt_val = _normalize_text(opt.get("value", ""))
                opt_label = _normalize_text(opt.get("label", ""))
                # Match canonical value (e.g. "adult_female" in "adult_female")
                # OR match label tokens (e.g. "dama" in "dama / senora")
                # OR the option value is contained in the hint (substring match)
                if (
                    hint_lower in opt_val
                    or opt_val in hint_lower
                    or hint_lower in opt_label
                    or _label_tokens_match(hint_lower, opt_label)
                    or _label_tokens_match(user_text, opt_label)
                ):
                    _apply_resolved_option(ctx, opt, axis, audience_hint)
                    matched = True
                    resolved_any = True
                    break
            if not matched:
                still_pending.append(clarification)
            continue

        # ── hair_density axis: scan user_text against hint map ──
        if axis == "hair_density":
            resolved_value = _match_hint_map(user_text, _HAIR_DENSITY_HINT_MAP)
            if resolved_value:
                options = clarification.get("options", [])
                matched = False
                for opt in options:
                    if _normalize_text(opt.get("value")) == resolved_value:
                        _apply_resolved_option(ctx, opt, axis, resolved_value)
                        matched = True
                        resolved_any = True
                        break
                if not matched:
                    still_pending.append(clarification)
            else:
                still_pending.append(clarification)
            continue

        # ── hair_length axis: scan user_text against hint map ──
        if axis == "hair_length":
            resolved_value = _match_hint_map(user_text, _HAIR_LENGTH_HINT_MAP)
            if resolved_value:
                options = clarification.get("options", [])
                matched = False
                for opt in options:
                    if _normalize_text(opt.get("value")) == resolved_value:
                        _apply_resolved_option(ctx, opt, axis, resolved_value)
                        matched = True
                        resolved_any = True
                        break
                if not matched:
                    still_pending.append(clarification)
            else:
                still_pending.append(clarification)
            continue

        # ── Unknown axis: keep as-is ──
        still_pending.append(clarification)

    if resolved_any:
        ctx.pending_clarifications = still_pending

    return resolved_any


def _label_tokens_match(user_normalized: str, label_normalized: str) -> bool:
    """Return True if any word-token from user_normalized appears in label_normalized.

    Used to match user answers like "dama" against option labels like "dama / senora".
    Only considers tokens of 4+ characters to avoid false positives from short words.
    """
    if not user_normalized or not label_normalized:
        return False
    tokens = re.split(r"\W+", user_normalized)
    return any(
        len(tok) >= 4 and re.search(rf"\b{re.escape(tok)}\b", label_normalized) for tok in tokens
    )


def _match_hint_map(normalized_text: str, hint_map: dict[str, str]) -> str | None:
    """Scan normalized_text for keys in hint_map, longest match wins.

    Returns the axis value (e.g. "normal", "extra", "short_medium", "long")
    if a match is found, None otherwise. Prefers longer keys to avoid
    false positives from short substrings.
    """
    best_key: str | None = None
    best_len = 0
    for key, value in hint_map.items():
        if key in normalized_text and len(key) > best_len:
            best_key = key
            best_len = len(key)
    return hint_map[best_key] if best_key else None


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
    logger.info(
        "resolve_pending_clarification: auto-resolved '%s' "
        "via axis '%s'='%s' (remaining_pending=%d)",
        opt["service_name"],
        axis,
        resolved_value,
        len(ctx.pending_clarifications),
    )


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


def extract_slot_fields(result: dict, ctx: BookingContext) -> None:
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
        # Exception: needs_availability_refresh=True (set by SLOT_TAKEN) forces
        # the overwrite so a fresh availability check replaces stale slots.
        if ctx.offered_slots and not ctx.needs_availability_refresh:
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

    # find_next_available v4.2: soonest_any
    soonest_any = result.get("soonest_any")
    if soonest_any and isinstance(soonest_any, dict):
        stylist_name = soonest_any.get("stylist_name") or soonest_any.get("stylist", "")
        date_str = soonest_any.get("date", "")
        time_str = soonest_any.get("time", "")
        ctx.soonest_any_slot = f"{date_str} a las {time_str} con {stylist_name}"
        logger.info("extract_slot_fields: soonest_any = %s", ctx.soonest_any_slot)


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

    # Detect "customer not found" responses from action='get' — no "id" or "first_name"
    # will be extracted, so treat this as a failed attempt for circuit-breaker purposes.
    # Without this check the counter never increments and the agent can loop indefinitely
    # re-issuing action='get' instead of switching to action='create'.
    if result.get("exists") is False:
        ctx.manage_customer_failure_count += 1
        logger.warning(
            "extract_customer_fields: customer not found (exists=False, count=%d): %s",
            ctx.manage_customer_failure_count,
            result.get("message", "no message"),
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
