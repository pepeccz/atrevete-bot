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
import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.services.availability_service import _load_lead_time_min_days
from agent.services.policy_service import (
    accept_policy,
    get_conversation_policy_acceptance,
    set_conversation_policy_acceptance,
)
from agent.tools._booking_validators import (
    ERROR_ADVANCE_POLICY_VIOLATED,
    ERROR_CLOSED_DAY,
    ERROR_INVALID_RELATIVE_DATE,
    validate_booking_date,
    validate_service_ids_exist,
    validate_slot_in_offered,
    validate_stylist_id_exists,
)
from agent.tools._rejection_strikes import apply_rejection_strike_json
from agent.tools.schemas import ToolResponse
from shared.config import get_settings

_MADRID_TZ = ZoneInfo("Europe/Madrid")

# Defense-in-depth: detect UUID strings that the model accidentally puts in `services`
# instead of `pre_resolved_service_ids`. These are re-routed rather than rejected so the
# booking flow is not broken by model echo behaviour (see booking_flow.md R-36b fix).
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


async def _persist_policy_acceptance(
    session,
    customer_id: str | None,
    conversation_id: str | None,
    policy_version: str,
) -> None:
    """Best-effort durable persistence of policy acceptance at gate-clear time (L2).

    Two layers, both fail-open (durability must never block the booking flow —
    the round-trip flag in `collected` remains the primary carrier):
    1. DB truth — when the customers row already exists, write
       Customer.policy_accepted_at + a CustomerConsent row immediately.
    2. Conversation marker — Redis key covering brand-new customers that have
       no customers row until book() creates one.
    """
    if customer_id:
        try:
            await accept_policy(
                db=session,
                customer_id=customer_id,
                policy_version=policy_version,
                accepted_via="whatsapp",
                source_message_id=None,
            )
            await session.commit()
        except Exception as exc:
            logger.error(
                "policy acceptance DB persist failed at gate clear (fail-open): %s",
                exc,
                exc_info=True,
            )
            try:
                await session.rollback()
            except Exception as rollback_exc:
                # Never let a rollback failure mask the original persist error log.
                logger.error(
                    "session rollback failed after policy persist failure: %s",
                    rollback_exc,
                    exc_info=True,
                )
    if conversation_id:
        await set_conversation_policy_acceptance(conversation_id, policy_version)


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
    policy_accepted: bool = False,
    policy_rejection_count: int = 0,
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
        policy_accepted: Round-trip flag — set True when the customer has accepted the
            privacy/booking policy. Gate clears and flow continues. Default False.
        policy_rejection_count: Round-trip counter of how many times the customer has
            declined the policy. Gate escalates at >= 2. Default 0.

    Returns:
        JSON-serialized ToolResponse with status, collected, missing, next_step.
        Valid next_step values: service_required | category_mix_required |
        audience_required | variant_required | stylist_required | offer_slots |
        date_required | closed_day_required | advance_policy_violated | name_required | extras_loop_required |
        notes_optional | pre_book_validation_required | date_clarification_required | booking_ready |
        policy_acceptance_required | policy_escalation_required.
    """
    _state = state or {}
    messages = _state.get("messages", [])
    try:
        raw = await _update_booking_impl(
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
            policy_accepted=policy_accepted,
            policy_rejection_count=policy_rejection_count,
            customer_id=_state.get("customer_id"),
            conversation_id=_state.get("conversation_id"),
            recently_offered_slots=_state.get("recently_offered_slots") or [],
            customer_memories=_state.get("customer_memories"),
        )
        # N3 — strike layer: the 2nd consecutive identical rejection becomes an
        # explicit escalation directive (deterministic exit from rejection loops).
        return apply_rejection_strike_json(raw, messages, "update_booking")
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
    policy_accepted: bool = False,
    policy_rejection_count: int = 0,
    customer_id: str | None = None,
    conversation_id: str | None = None,
    recently_offered_slots: list[dict] | None = None,
    customer_memories: dict | None = None,
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
        gendered_service_without_audience_source,
    )
    from database.connection import get_async_session

    # C1 fix: callers using pre_resolved_service_ids only may pass services=None.
    # Default to [] so subsequent iteration (Steps 1/2 audience/variant loops) is safe.
    services = services or []

    # Defense-in-depth: re-route UUID strings that leaked into `services`.
    # The model sometimes echoes collected.service_ids (UUIDs) back into the `services`
    # field on policy-acceptance round-trips (booking_flow.md R-36b).  Name resolution
    # (_resolve_service_ids_strict) does not match UUIDs → unknown_names rejection.
    # Fix: detect UUID-format entries, strip them from `services`, and merge them into
    # `pre_resolved_service_ids` so they go through the existing DB-existence gate.
    _leaked_uuids = [s for s in services if _UUID_RE.match(s)]
    if _leaked_uuids:
        logger.warning(
            "tool.uuid_reroute",
            extra={
                "tool_name": "update_booking",
                "leaked_uuids": _leaked_uuids,
                "conversation_id": conversation_id,
            },
        )
        services = [s for s in services if not _UUID_RE.match(s)]
        # Merge leaked UUIDs into pre_resolved_service_ids (preserve order, dedupe).
        existing_pre = list(pre_resolved_service_ids) if pre_resolved_service_ids else []
        existing_set = set(u.lower() for u in existing_pre)
        for _u in _leaked_uuids:
            if _u.lower() not in existing_set:
                existing_pre.append(_u)
                existing_set.add(_u.lower())
        pre_resolved_service_ids = existing_pre if existing_pre else None

    async with get_async_session() as session:
        collected: dict = {}
        missing: list[str] = []
        errors: list[str] = []

        # ── AR5: validate pre_resolved_service_ids against active catalog ─────
        # UUIDs are validated BEFORE the services gate so that pre_resolved can
        # satisfy the services requirement (ADR-DR-2). Invalid UUIDs are rejected
        # immediately to prevent hallucinated UUIDs bypassing catalog validation.
        pre_resolved_set: list[str] = []
        if pre_resolved_service_ids:
            from sqlalchemy import select as _sa_select

            from database.models import Service as _Service

            _uuid_list: list[str] = list(pre_resolved_service_ids)
            _result = await session.execute(
                _sa_select(_Service.id).where(
                    _Service.id.in_(_uuid_list),
                    _Service.is_active.is_(True),
                )
            )
            valid_ids = {str(r[0]) for r in _result.fetchall()}
            invalid = [u for u in _uuid_list if u not in valid_ids]
            if invalid:
                logger.info(
                    "tool.response.rejected",
                    extra={
                        "tool_name": "update_booking",
                        "next_step": "service_required",
                        "invalid_pre_resolved_ids": invalid,
                    },
                )
                return ToolResponse(
                    status="rejected",
                    errors=[f"UUIDs no válidos o inactivos: {invalid}"],
                    next_step="service_required",
                ).model_dump_json()
            pre_resolved_set = list(valid_ids)
            logger.info(
                "tool.disambiguation.pre_resolved_merged",
                extra={
                    "tool_name": "update_booking",
                    "pre_resolved_count": len(pre_resolved_set),
                    "pre_resolved_ids": pre_resolved_set,
                },
            )

        # ── Step 3: no services ───────────────────────────────────────────────
        # pre_resolved_set satisfies the services requirement if non-empty.
        if not services and not pre_resolved_set:
            missing.append("services")
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=missing,
                next_step="service_required",
            ).model_dump_json()

        # ── Resolve service names (strict: detects ambiguous axis at resolution time) ──
        # When services is empty (only pre_resolved_set), skip name resolution entirely.
        if services:
            resolved_ids, unknown_names, ambiguous_descriptors, partial_resolved_ids = (
                await _resolve_service_ids_strict(session, services, audience=audience)
            )
        else:
            resolved_ids, unknown_names, ambiguous_descriptors, partial_resolved_ids = (
                [],
                [],
                [],
                [],
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

        # ── ADR-DR-2: merge pre_resolved_set into resolved_ids ───────────────
        # De-duplicate by UUID to prevent double-booking the same service.
        if pre_resolved_set:
            existing = set(resolved_ids)
            for _uuid in pre_resolved_set:
                if _uuid not in existing:
                    resolved_ids.append(_uuid)
                    existing.add(_uuid)

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

        # ── Step 1.6: audience-source gate (deterministic cold-guess catch) ──
        # A GENDERED service (a principal in a multi-audience dimension whose own
        # audience is set, e.g. "Corte de Mujer") resolved with audience=None is
        # only legitimate when the customer has a real audience SOURCE: memory
        # backing (typical_services/agent_notes) or a prior appointment with that
        # audience. With a source it is the loyal-customer echo ("lo de siempre")
        # and must NOT be re-asked. Without a source it is a cold GUESS by the
        # model → ask. This closes the residual path where the model passes
        # services=["corte de mujer"] straight into update_booking. The neutral
        # family token ("corte") is already handled earlier (Step 1.7). See R32.
        if audience is None and resolved_ids:
            try:
                _gendered = await gendered_service_without_audience_source(
                    session,
                    resolved_ids,
                    customer_memories=customer_memories,
                    customer_id=customer_id,
                )
            except Exception as exc:
                # Fail-open: an auxiliary source check must never kill a booking
                # turn. On error we skip the gate (the resolution query already
                # succeeded, so this path is normally healthy).
                logger.error(
                    "update_booking: audience-source gate failed (fail-open): %s",
                    exc,
                    exc_info=True,
                )
                _gendered = None
            if _gendered is not None:
                _family_label, _candidates = _gendered
                logger.info(
                    "tool.response.rejected",
                    extra={
                        "tool_name": "update_booking",
                        "next_step": "audience_required",
                        "reason": "no_audience_source",
                    },
                )
                return ToolResponse(
                    status="rejected",
                    next_step="audience_required",
                    payload={"variants": _candidates, "family": _family_label},
                ).model_dump_json()

        # ── Step 1 (REMOVED): the legacy memory-blind audience gate lived here ─
        # It called `_resolve_audience_variants(service_name)` WITHOUT input_audience
        # and re-fired `audience_required` for any multi-audience principal. That
        # defeated the loyal-customer echo: a returning customer whose memory backs
        # the audience passes Step 1.6 (source-aware), only to be re-asked here.
        # The audience axis is now fully owned by:
        #   - Step 1.7 (`_resolve_service_ids_strict`): neutral/null-audience family
        #     tokens (e.g. "corte") → audience_required ambiguous descriptor.
        #   - Step 1.6 (`gendered_service_without_audience_source`): gendered service
        #     with no legitimate audience source (cold model guess) → audience_required.
        # No remaining case relies on this blind gate; keeping it only broke source (a).

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

        # ── J1: FK existence guard — service_ids ─────────────────────────────
        # Validates that every resolved UUID actually exists in the services table.
        # Defends against hallucinated UUIDs that might have bypassed name resolution.
        if resolved_ids:
            from uuid import UUID as _UUID

            _parsed_service_ids = []
            for _sid in resolved_ids:
                try:
                    _parsed_service_ids.append(_UUID(str(_sid)))
                except (ValueError, AttributeError):
                    pass
            if _parsed_service_ids:
                _svc_fk_result = await validate_service_ids_exist(session, _parsed_service_ids)
                if not _svc_fk_result.ok:
                    logger.info(
                        "tool.response.rejected",
                        extra={
                            "tool_name": "update_booking",
                            "next_step": "invalid_service_ids",
                        },
                    )
                    return ToolResponse(
                        status="rejected",
                        next_step="service_required",
                        errors=[_svc_fk_result.error_message],
                        payload={
                            "missing_service_ids": [str(u) for u in _svc_fk_result.missing_ids],
                            **_svc_fk_result.payload,  # N3: valid_candidates ground truth
                        },
                    ).model_dump_json()

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
            # J1: FK existence guard — stylist_id
            from uuid import UUID as _UUID2

            try:
                _parsed_stylist_id = _UUID2(str(stylist_id))
                _sty_fk_result = await validate_stylist_id_exists(session, _parsed_stylist_id)
                if not _sty_fk_result.ok:
                    logger.info(
                        "tool.response.rejected",
                        extra={
                            "tool_name": "update_booking",
                            "next_step": "stylist_required",
                        },
                    )
                    return ToolResponse(
                        status="rejected",
                        collected=collected,
                        missing=["stylist"],
                        next_step="stylist_required",
                        errors=[_sty_fk_result.error_message],
                    ).model_dump_json()
            except (ValueError, AttributeError):
                pass  # Invalid UUID already caught by _resolve_stylist

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
        _min_days = await _load_lead_time_min_days()
        _date_validation = await validate_booking_date(
            date_iso=date_iso,
            date_text=date_text,
            min_days=_min_days,
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

        # ── Step 6c: policy acceptance gate ──────────────────────────────────
        # Fires when slot_iso is set and the customer has not yet accepted the
        # current POLICY_VERSION. policy_accepted is the round-trip flag the LLM
        # sets after the customer's "sí". policy_rejection_count rolls forward from
        # the LLM with prior rejections; escalation triggers at >= 2.
        #
        # L2 (Change L): the LLM flag is hallucination-prone — it gets dropped
        # between tool calls (QA V4 re-ask loop). The durable conversation marker
        # written at gate-clear time recovers the acceptance when the flag is lost.
        if slot_iso is not None:
            _settings = get_settings()
            _customer_obj = None
            if customer_id:
                from database.models import Customer as _Customer

                _customer_obj = await session.get(_Customer, customer_id)

            needs_policy = (
                _customer_obj is None
                or _customer_obj.policy_accepted_at is None
                or _customer_obj.policy_version != _settings.POLICY_VERSION
            )

            effective_policy_accepted = policy_accepted
            if needs_policy and not effective_policy_accepted and conversation_id:
                _marker_version = await get_conversation_policy_acceptance(conversation_id)
                if _marker_version == _settings.POLICY_VERSION:
                    logger.info(
                        "policy gate: acceptance recovered from conversation marker",
                        extra={"tool_name": "update_booking"},
                    )
                    effective_policy_accepted = True

            if needs_policy and not effective_policy_accepted:
                if policy_rejection_count >= 2:
                    logger.info(
                        "tool.response.partial",
                        extra={
                            "tool_name": "update_booking",
                            "next_step": "policy_escalation_required",
                            "policy_rejection_count": policy_rejection_count,
                        },
                    )
                    return ToolResponse(
                        status="partial",
                        collected=collected,
                        missing=[],
                        next_step="policy_escalation_required",
                        payload={
                            "reason": "policy_rejection",
                            "policy_rejection_count": policy_rejection_count,
                        },
                    ).model_dump_json()

                logger.info(
                    "tool.response.partial",
                    extra={
                        "tool_name": "update_booking",
                        "next_step": "policy_acceptance_required",
                        "policy_rejection_count": policy_rejection_count,
                    },
                )
                return ToolResponse(
                    status="partial",
                    collected=collected,
                    missing=[],
                    next_step="policy_acceptance_required",
                    payload={
                        "policy_url": _settings.POLICY_URL,
                        "policy_version": _settings.POLICY_VERSION,
                        "policy_rejection_count": policy_rejection_count,
                    },
                ).model_dump_json()

            # Gate cleared — persist acceptance durably and carry the flag forward.
            # Persistence happens ONLY when the gate was actually pending (needs_policy):
            # repeated round-trip calls after acceptance skip the writes.
            if effective_policy_accepted:
                if needs_policy:
                    await _persist_policy_acceptance(
                        session=session,
                        customer_id=customer_id,
                        conversation_id=conversation_id,
                        policy_version=_settings.POLICY_VERSION,
                    )
                collected["policy_accepted"] = True
                collected["policy_version_accepted"] = _settings.POLICY_VERSION

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

        # ── J3: slot-binding guard (recently_offered_slots) ──────────────────
        # Validates that slot_iso was actually offered to the customer in this session.
        # Runs BEFORE the DB recheck to fail-fast on hallucinated slots.
        _offered = recently_offered_slots or []
        _slot_result = validate_slot_in_offered(slot_iso, resolved_stylist_id, _offered)
        if not _slot_result.ok:
            logger.info(
                "tool.response.partial",
                extra={
                    "tool_name": "update_booking",
                    "next_step": "reoffer_slots",
                },
            )
            return ToolResponse(
                status="partial",
                collected=collected,
                missing=[],
                next_step="reoffer_slots",
                errors=[_slot_result.error_message],
            ).model_dump_json()

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
