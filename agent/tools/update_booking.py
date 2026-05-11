"""Slot collector tool for the booking flow.

Accepts any subset of booking slots, validates them against the DB, and returns
a ToolResponse describing which slots were collected and which are still missing.
Idempotent: safe to call repeatedly. Does NOT create appointments.

Priority matrix (first matching rule wins):
1. No services → partial, service_required
1.5. Mixed HAIRDRESSING + AESTHETICS services → rejected, category_mix_required  [NEW]
2. Ambiguous service family + no audience → rejected, audience_required
3. Services present + no stylist + no_preference=False → partial, stylist_required
4. Services + stylist + no date → partial, date_required
5. All present → ok, booking_ready

Refs: R2, R3, design §5
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.tools._booking_validators import (
    ERROR_ADVANCE_POLICY_VIOLATED,
    ERROR_CLOSED_DAY,
    ERROR_INVALID_RELATIVE_DATE,
    validate_booking_date,
)
from agent.tools.schemas import ToolResponse

_MADRID_TZ = ZoneInfo("Europe/Madrid")

logger = logging.getLogger(__name__)


def _parse_iso_to_utc(s: str) -> datetime | None:
    """Parse an ISO 8601 string to a UTC-aware datetime, or return None on any failure.

    - Falsy or non-string input → None.
    - Normalizes trailing 'Z' to '+00:00' (defensive shim; Python 3.11 fromisoformat
      handles Z natively, but the explicit replace is cheap and readable).
    - Naive datetime (no tzinfo) → None (fail-closed; see design ADR-2).
    - ValueError → None (fail-closed).
    Never raises.
    """
    if not s or not isinstance(s, str):
        return None
    try:
        normalized = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        logger.warning(
            "gate.naive_iso_denied",
            extra={"slot_iso": s},
        )
        return None
    return dt.astimezone(UTC)


def _find_matching_check_availability(
    messages: list,
    slot_iso: str | None,
    stylist_id: str | None,
) -> bool:
    """Scan the full message history for a check_availability ToolMessage confirming the slot.

    Returns True if a matching confirmation is found, False otherwise.
    Comparison is UTC-normalized datetime equality — no substring matching.
    Full scan (no fixed-size tail slice): SummarizeMiddleware already bounds history to ~20 msgs.

    A message matches if:
    - name == "check_availability"
    - status == "ok"
    - UTC-normalized slot datetime equals UTC-normalized slot_iso
    - slot.stylist_id matches stylist_id (when both are provided)
    """
    if not messages or not slot_iso:
        return False

    slot_dt = _parse_iso_to_utc(slot_iso)
    if slot_dt is None:
        # slot_iso is malformed or naive — fail-closed
        return False

    for msg in messages:
        if not hasattr(msg, "name") or msg.name != "check_availability":
            continue
        try:
            data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
        except (json.JSONDecodeError, TypeError):
            continue

        if data.get("status") != "ok":
            continue

        payload = data.get("payload", {})
        slots = payload.get("slots", [])
        for s in slots:
            s_dt = _parse_iso_to_utc(s.get("start_iso", ""))
            if s_dt is None:
                continue
            if s_dt != slot_dt:
                continue
            s_stylist = s.get("stylist_id", "")
            stylist_match = (
                stylist_id is None or s_stylist is None or str(s_stylist) == str(stylist_id)
            )
            if stylist_match:
                return True

    return False


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
    slot_iso: str | None = None,
    variant_resolved: bool = False,
    pre_resolved_service_ids: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """Slot collector for the booking flow.

    Pass any subset of booking slots; returns what was collected, what is missing,
    and the next descriptive state in `next_step`. Safe to call repeatedly —
    idempotent. Does NOT create appointments; call `book` (with confirmed=True) for that.

    Args:
        services: List of service names requested (e.g. ["corte dama", "peinado"]).
            Para servicios con variantes por longitud (peinados, recogidos),
            ver `agent/prompts/shared/glossary.md § Mapeo longitud → variante`.
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
        slot_iso: Optional full ISO datetime of the slot the customer has chosen (e.g.
            "2026-05-01T10:00:00+02:00"). Required to activate the pre_book_validation_required
            gate. Pass when the customer has selected a specific slot and you are ready to book.
        variant_resolved: Set True when the user has explicitly accepted the principal service
            as-is (e.g. "mechas normales" after a variant_required turn). When True, the
            variant gate is bypassed and the principal UUID is committed directly.
            Default False preserves current behavior (gate fires).
            Refs: REQ-TL-1, ADR-DR-1.
        pre_resolved_service_ids: UUIDs from a previous turn's collected.partial_resolved_ids.
            These bypass name resolution entirely and are merged directly into collected.services.
            Each UUID is validated against the active service catalog before merge.
            Default None (treated as empty list) preserves current behavior.
            Refs: REQ-TL-2, ADR-DR-2.

    Returns:
        JSON-serialized ToolResponse with status, collected, missing, next_step.
        Valid next_step values: service_required | category_mix_required |
        audience_required | variant_required | stylist_required | offer_slots |
        date_required | closed_day_required | advance_policy_violated | name_required | extras_loop_required |
        notes_optional | pre_book_validation_required | date_clarification_required | booking_ready.
    """
    messages = (state or {}).get("messages", [])
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
            slot_iso=slot_iso,
            variant_resolved=variant_resolved,
            pre_resolved_service_ids=pre_resolved_service_ids,
            messages=messages,
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
    slot_iso: str | None = None,
    variant_resolved: bool = False,
    pre_resolved_service_ids: list[str] | None = None,
    messages: list | None = None,
) -> str:
    from agent.booking.resolvers.time_resolver import MIN_BOOKING_DAYS
    from agent.tools._booking_helpers import (
        _resolve_active_stylists,
        _resolve_audience_variants,
        _resolve_service_categories,
        _resolve_service_id_to_category_map,
        _resolve_service_ids,
        _resolve_service_ids_strict,
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

        # ── Resolve service names (strict: detects ambiguous axis at resolution time) ──
        resolved_ids, unknown_names, ambiguous_descriptors, partial_resolved_ids = (
            await _resolve_service_ids_strict(session, services)
        )

        # ── Step 1.7: ambiguous descriptor gate (audience or variant axis) ────
        # _resolve_service_ids_strict already detected the axis without committing
        # a UUID. Apply variant_resolved bypass (ADR-DR-1) before returning.
        if ambiguous_descriptors:
            # ADR-DR-1: when variant_resolved=True, bypass the variant gate for the
            # first ambiguous variant descriptor — commit the principal UUID directly.
            if variant_resolved:
                remaining_ambiguous = []
                for desc in ambiguous_descriptors:
                    if desc["axis"] == "variant":
                        # Commit the principal UUID by resolving the service_term name
                        from agent.tools._booking_helpers import _resolve_service_ids

                        principal_ids, _unk = await _resolve_service_ids(
                            session, [desc["service_term"]]
                        )
                        if principal_ids:
                            resolved_ids.extend(principal_ids)
                            logger.info(
                                "tool.disambiguation.principal_accepted",
                                extra={
                                    "tool_name": "update_booking",
                                    "service_term": desc["service_term"],
                                    "principal_uuid": principal_ids[0],
                                },
                            )
                        # Do not add to remaining_ambiguous — descriptor is consumed
                    else:
                        remaining_ambiguous.append(desc)
                ambiguous_descriptors = remaining_ambiguous

        if ambiguous_descriptors:
            first_desc = ambiguous_descriptors[0]
            next_step = first_desc["question_hint"]  # "audience_required" | "variant_required"
            logger.info(
                "tool.response.ambiguous",
                extra={
                    "tool_name": "update_booking",
                    "next_step": next_step,
                    "axis": first_desc["axis"],
                    "candidates_count": len(first_desc["candidates"]),
                },
            )
            # NFR-2: emit partial_committed audit log when partial_resolved_ids is non-empty
            if partial_resolved_ids:
                logger.info(
                    "tool.disambiguation.partial_committed",
                    extra={
                        "tool_name": "update_booking",
                        "partial_resolved_ids": partial_resolved_ids,
                        "count": len(partial_resolved_ids),
                    },
                )
            return ToolResponse(
                status="ambiguous",
                next_step=next_step,
                payload=first_desc,
                collected={"partial_resolved_ids": partial_resolved_ids},
            ).model_dump_json()

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

        # ── Step 1.5: category-mix gate ──────────────────────────────────────
        # Runs AFTER service resolution (needs UUIDs) and BEFORE audience/variant gates.
        # Fails-closed when services span HAIRDRESSING + AESTHETICS (no BOTH override).
        from database.models import ServiceCategory as _SC

        _service_categories = await _resolve_service_categories(session, resolved_ids)
        _has_hair = _SC.HAIRDRESSING in _service_categories
        _has_aesth = _SC.AESTHETICS in _service_categories
        if _has_hair and _has_aesth:
            # Build payload: map each input service name to its category via bulk query.
            _id_to_cat = await _resolve_service_id_to_category_map(session, resolved_ids)
            _hair_services: list[str] = []
            _aesth_services: list[str] = []
            _both_services: list[str] = []
            for _svc_name, _svc_id in zip(services, resolved_ids, strict=False):
                _cat = _id_to_cat.get(_svc_id)
                if _cat == _SC.HAIRDRESSING:
                    _hair_services.append(_svc_name)
                elif _cat == _SC.AESTHETICS:
                    _aesth_services.append(_svc_name)
                else:  # BOTH or unknown — include in both groups per ADR-4
                    _both_services.append(_svc_name)
            logger.info(
                "tool.response.rejected",
                extra={"tool_name": "update_booking", "next_step": "category_mix_required"},
            )
            return ToolResponse(
                status="rejected",
                next_step="category_mix_required",
                payload={
                    "hairdressing_services": _hair_services + _both_services,
                    "aesthetics_services": _aesth_services + _both_services,
                    "categories": ["HAIRDRESSING", "AESTHETICS"],
                },
                errors=["No puedo combinar peluquería y estética en una misma cita."],
            ).model_dump_json()

        # ── Step 1: audience disambiguation (only when audience unknown) ─────
        # kind=="audience" → multi-PRINCIPAL same-dimension, ask for audience.
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

        # ── Step 2: variant disambiguation — UNGATED (independent of audience) ─
        # kind=="variant" → principal with active children OR child with siblings.
        # Must run regardless of audience state — the two axes are orthogonal.
        # Design: ADR-2 ordering (booking-disambiguation-hardening).
        for service_name in services:
            kind, family, candidates = await _resolve_audience_variants(session, service_name)
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
                _first_available_label = (
                    f"La primera con disponibilidad (mín. {MIN_BOOKING_DAYS} días de antelación)"
                )
                return ToolResponse(
                    status="rejected",
                    collected=collected,
                    missing=["stylist"],
                    next_step="stylist_required",
                    errors=[f"No encontré a la estilista: {stylist_name}"],
                    payload={
                        "stylists": await _resolve_active_stylists(
                            session, service_ids=resolved_ids
                        ),
                        "first_available_label": _first_available_label,
                    },
                ).model_dump_json()
            collected["stylist_id"] = str(stylist_id)
            collected["stylist_name"] = stylist_name

        if not no_preference_stylist and stylist_id is None:
            missing.append("stylist")
            _first_available_label = (
                f"La primera con disponibilidad (mín. {MIN_BOOKING_DAYS} días de antelación)"
            )
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=missing,
                next_step="stylist_required",
                payload={
                    "stylists": await _resolve_active_stylists(session, service_ids=resolved_ids),
                    "first_available_label": _first_available_label,
                },
            ).model_dump_json()

        if no_preference_stylist:
            collected["no_preference_stylist"] = True

        # ── Step 6b: no date — offer_slots when stylist is resolved ──────────
        # When a stylist (or no-preference) is set and no date is provided, signal the LLM
        # to call get_next_available_options immediately using the payload below.
        # next_step="date_required" is only the 0-options fallback, driven by prompt rules.
        if not date_iso and not date_text:
            missing.append("date_iso")
            stylist_resolved = bool(collected.get("stylist_id")) or bool(
                collected.get("no_preference_stylist")
            )
            if stylist_resolved:
                today_iso = datetime.now(_MADRID_TZ).date().isoformat()
                return ToolResponse(
                    status="partial",
                    collected=collected,
                    missing=missing,
                    next_step="offer_slots",
                    payload={
                        "stylist_id": collected.get("stylist_id"),
                        "no_preference_stylist": bool(collected.get("no_preference_stylist")),
                        "service_ids": collected.get("service_ids", []),
                        "from_date": today_iso,
                        "min_advance_days": MIN_BOOKING_DAYS,
                    },
                ).model_dump_json()
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=missing,
                next_step="date_required",
            ).model_dump_json()

        # ── Steps 6, 6c, 6d: date resolution + G1/G2/G3 via shared validator ──
        # validate_booking_date resolves relative text (G1), checks closed days (G2),
        # and enforces lead-time policy (G3). Short-circuits on first failure.
        # The adapter maps canonical error codes to this tool's wire-format next_step values.
        _date_validation = await validate_booking_date(
            date_iso=date_iso,
            date_text=date_text,
        )

        if not _date_validation.ok:
            # Adapter mapping: canonical error codes → prompt-graph next_step values (ADR-2, ADR-6)
            _next_step_map = {
                ERROR_INVALID_RELATIVE_DATE: "date_clarification_required",
                ERROR_CLOSED_DAY: "closed_day_required",
                ERROR_ADVANCE_POLICY_VIOLATED: "advance_policy_violated",
            }
            _next_step = _next_step_map.get(
                _date_validation.error_code, "date_required"  # fallback for unknown codes
            )

            # Build caller-owned payload: validator payload + tool-specific context
            _resolved_rejected = date_iso or (
                _date_validation.payload.get("raw_text", date_text) or date_text or ""
            )
            if _date_validation.error_code == ERROR_CLOSED_DAY:
                # Preserve the full payload shape expected by the prompt graph
                _closed_iso = _date_validation.payload.get("closed_date", date_iso)
                _closed_date = datetime.fromisoformat(_closed_iso).date() if _closed_iso else None
                _adapter_payload = {
                    "rejected_date": _closed_iso,
                    "weekday": _closed_date.strftime("%A").lower() if _closed_date else "",
                    "stylist_id": collected.get("stylist_id"),
                    "service_ids": collected.get("service_ids", []),
                }
            elif _date_validation.error_code == ERROR_ADVANCE_POLICY_VIOLATED:
                _adapter_payload = {
                    "rejected_date": date_iso,
                    "first_valid_date": _date_validation.payload.get("min_date", ""),
                    "policy_min_days": _date_validation.payload.get("min_days", MIN_BOOKING_DAYS),
                    "stylist_id": collected.get("stylist_id"),
                    "service_ids": collected.get("service_ids", []),
                }
            else:
                # G1: date_clarification_required — no extra payload needed
                _adapter_payload = {}

            logger.info(
                "tool.response.rejected",
                extra={"tool_name": "update_booking", "next_step": _next_step},
            )
            _is_g1 = _date_validation.error_code == ERROR_INVALID_RELATIVE_DATE
            return ToolResponse(
                status="partial" if _is_g1 else "rejected",
                collected=collected,
                missing=["date_iso"],
                next_step=_next_step,
                payload=_adapter_payload,
                errors=[_date_validation.error_message] if _date_validation.error_message else [],
            ).model_dump_json()

        # Validation passed — use the canonical resolved date
        date_iso = _date_validation.date_iso
        collected["date_iso"] = date_iso

        # ── Step 7: name required — after stylist+date+closed-day-check ──────
        # name_required intentionally fires AFTER date_iso is resolved AND closed-day-validated.
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

        # ── Step 8b: pre-book validation gate (ADR-6) ─────────────────────────
        # slot_iso=None means the LLM hasn't chosen a slot yet — gate always blocks.
        # slot_iso provided → must have a matching check_availability ToolMessage.
        if slot_iso is None:
            logger.info(
                "tool.response.partial",
                extra={
                    "tool_name": "update_booking",
                    "next_step": "pre_book_validation_required",
                },
            )
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=[],
                next_step="pre_book_validation_required",
                payload={
                    "hint": (
                        "Llama a check_availability con slot_time exacto antes de book(). "
                        "No se ha proporcionado slot_iso."
                    ),
                },
            ).model_dump_json()

        resolved_stylist_id = collected.get("stylist_id")
        validated = _find_matching_check_availability(messages or [], slot_iso, resolved_stylist_id)

        if not validated:
            logger.info(
                "tool.response.partial",
                extra={
                    "tool_name": "update_booking",
                    "next_step": "pre_book_validation_required",
                },
            )
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=[],
                next_step="pre_book_validation_required",
                payload={
                    "hint": (
                        "Llama a check_availability con slot_time exacto antes de book(). "
                        f"Slot solicitado: {slot_iso}"
                    ),
                },
            ).model_dump_json()
        collected["pre_book_validated"] = True
        if slot_iso is not None:
            collected["slot_iso"] = slot_iso

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
