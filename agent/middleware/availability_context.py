"""AvailabilityContextMiddleware — inject grounded availability into the system prompt.

Reads the latest update_booking ToolMessage from conversation history to determine
resolved service_ids. When present, calls get_availability_window to fetch real
slot data and writes the result as _slot_availability (XML block) into state.

Cache: Redis key per (services_hash, audience, lead_window_start, days), TTL 60s.
Best-effort invalidation via TTL — pre-book gate (T5) is the correctness backstop.

Must be registered AFTER DynamicPromptMiddleware and BEFORE PromptAssemblyMiddleware.
Spec: R1.1–R1.5, R1.7. Design: ADR-1, ADR-3, ADR-4.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar
from uuid import UUID

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from agent.services.availability_service import get_availability_window

logger = logging.getLogger(__name__)

_CACHE_TTL = 60  # seconds
_MAX_DAY_LINES = 30  # token-budget guard (ADR-3)

_WEEKDAYS_ES_LONG = {
    "lunes": "lunes",
    "martes": "martes",
    "miércoles": "miércoles",
    "jueves": "jueves",
    "viernes": "viernes",
    "sábado": "sábado",
    "domingo": "domingo",
}

_MONTH_NAMES_ES = [
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def _get_redis() -> Any | None:
    """Return the Redis client, or None if unavailable (best-effort cache)."""
    try:
        from shared.redis_client import get_redis_client

        return get_redis_client()
    except Exception:
        return None


def _build_cache_key(
    service_ids: list[str],
    audience: str | None,
    lead_window_start: str,
    days: int,
) -> str:
    """Derive a stable Redis cache key per ADR-4."""
    sids_sorted = ",".join(sorted(service_ids))
    sids_hash = hashlib.sha1(sids_sorted.encode()).hexdigest()[:12]
    aud = audience or "any"
    return f"availability:v1:{sids_hash}:{aud}:{lead_window_start}:{days}"


def _extract_service_ids_from_messages(messages: list) -> list[str] | None:
    """Walk messages in reverse to find the latest update_booking ToolMessage.

    Returns service_ids list if found and non-empty, else None.
    """
    for msg in reversed(messages):
        if not hasattr(msg, "name") or msg.name != "update_booking":
            continue
        try:
            data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
        except (json.JSONDecodeError, TypeError):
            continue

        collected = data.get("collected", {}) or {}
        sids = collected.get("service_ids")
        if sids and isinstance(sids, list) and len(sids) > 0:
            return sids

    return None


def _format_availability_xml(window: dict[str, list[dict]]) -> str:
    """Render the <availability> XML block from the aggregator result (ADR-3).

    Format per slot line: weekday D month (YYYY-MM-DD): HH:MM, HH:MM, ...
    """
    lines = ["<availability>", "## Próximos huecos (ventana 7 días)"]

    for stylist_name, day_entries in sorted(window.items()):
        lines.append(stylist_name)
        for entry in day_entries:
            date_iso = entry["date_iso"]
            weekday_es = entry["weekday_es"]
            slots_str = ", ".join(entry["slots"])
            # Parse date for Spanish month label
            try:
                d = date.fromisoformat(date_iso)
                month_es = _MONTH_NAMES_ES[d.month]
                date_label = f"{weekday_es} {d.day} {month_es} ({date_iso})"
            except (ValueError, IndexError):
                date_label = f"{weekday_es} ({date_iso})"
            lines.append(f"  {date_label}: {slots_str}")

    lines.append(
        "--- Huecos orientativos. Revalida con check_availability antes de proponer "
        "un slot concreto al cliente. ---"
    )
    lines.append("</availability>")
    return "\n".join(lines)


def _count_day_lines(window: dict) -> int:
    """Count total day-lines across all stylists."""
    return sum(len(day_entries) for day_entries in window.values())


# ---------------------------------------------------------------------------
# J3: recently_offered_slots producer helpers
# ---------------------------------------------------------------------------

_OFFERED_SLOT_TTL_MINUTES = 15
_OFFERED_SLOT_MAX_TURNS = 2  # purge entries older than current_turn - this


def _extract_offered_slots_from_messages(messages: list) -> list[dict]:
    """Scan message history for check_availability / get_next_available_options ToolMessages.

    Returns a list of slot dicts: {start_iso, stylist_id} for each confirmed slot.
    Only considers messages with name in ('check_availability', 'get_next_available_options').
    """
    slots: list[dict] = []
    for msg in messages:
        name = getattr(msg, "name", None)
        if name not in ("check_availability", "get_next_available_options"):
            continue
        try:
            data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
        except (json.JSONDecodeError, TypeError):
            continue

        # check_availability: {status: ok, payload: {slots: [...]}}
        if name == "check_availability":
            if data.get("status") != "ok":
                continue
            raw_slots = data.get("payload", {}).get("slots", [])
        else:
            # get_next_available_options returns a ToolResponse:
            # {status: ok, payload: {options: [...], ...}}
            # Each option has start_iso/stylist_id field names.
            if data.get("status") != "ok":
                continue
            raw_slots = data.get("payload", {}).get("options", [])

        for s in raw_slots:
            start_iso = s.get("start_iso") or s.get("start") or s.get("datetime")
            if not start_iso:
                continue
            stylist_id = s.get("stylist_id") or s.get("stylist") or None
            slots.append({"start_iso": start_iso, "stylist_id": stylist_id})

    return slots


def _materialize_offered_slots(
    new_raw_slots: list[dict],
    existing_slots: list[dict],
    current_turn_index: int,
    now: datetime,
) -> list[dict]:
    """Merge new raw slots with existing, applying TTL + turn-index purge.

    Purge rules (hybrid D1):
      - Wall-clock TTL: expires_at <= now → purge
      - Turn staleness: turn_index < current_turn_index - _OFFERED_SLOT_MAX_TURNS → purge

    New slots get:
      - expires_at = now + 15 min
      - turn_index = current_turn_index
    """
    expires_at = (now + timedelta(minutes=_OFFERED_SLOT_TTL_MINUTES)).isoformat()
    min_turn = current_turn_index - _OFFERED_SLOT_MAX_TURNS

    # Purge stale existing entries
    kept_existing: list[dict] = []
    for entry in existing_slots:
        # Wall-clock check
        expires_str = entry.get("expires_at", "")
        if expires_str:
            try:
                exp_dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00")).astimezone(UTC)
                if exp_dt <= now:
                    continue
            except ValueError:
                continue
        # Turn-index check
        if entry.get("turn_index", 0) < min_turn:
            continue
        kept_existing.append(entry)

    # Build new entries (de-duplicate by start_iso + stylist_id)
    existing_keys = {(e["start_iso"], e.get("stylist_id")) for e in kept_existing}

    for raw in new_raw_slots:
        key = (raw["start_iso"], raw.get("stylist_id"))
        if key not in existing_keys:
            kept_existing.append(
                {
                    "start_iso": raw["start_iso"],
                    "stylist_id": raw.get("stylist_id"),
                    "expires_at": expires_at,
                    "turn_index": current_turn_index,
                }
            )
            existing_keys.add(key)

    return kept_existing


def _update_offered_slots_in_state(state: dict, messages: list) -> dict:
    """Materialize recently_offered_slots from ToolMessages and merge with existing state slots.

    Returns a new state dict if any update is needed, otherwise returns the same dict.
    This is a pure-data transformation: no I/O.
    """
    new_raw = _extract_offered_slots_from_messages(messages)
    existing = state.get("recently_offered_slots") or []
    current_turn_index = len(messages)
    now = datetime.now(UTC)

    merged = _materialize_offered_slots(new_raw, existing, current_turn_index, now)

    # Only update state if something actually changed
    if merged != existing:
        return {**state, "recently_offered_slots": merged}
    return state


class AvailabilityContextMiddleware(AgentMiddleware):
    """Inject grounded <availability> XML block when booking context is active.

    Trigger: latest update_booking ToolMessage has non-empty service_ids in collected.
    No trigger: no update_booking ToolMessage, or service_ids is empty/absent.
    """

    _allow_single_variant: ClassVar[bool] = True

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state or {}
        messages = state.get("messages", [])

        service_ids = _extract_service_ids_from_messages(messages)
        if not service_ids:
            # Early-turn lean: no service resolved yet — still update offered slots
            updated_state = _update_offered_slots_in_state(state, messages)
            if updated_state is not state:
                return await handler(request.override(state=updated_state))
            return await handler(request)

        audience: str | None = None  # audience not tracked in state post-rework

        # Determine window params (apply token-budget guard ADR-3)
        days = 7
        max_slots_per_day = 4

        try:
            from agent.services.availability_service import _load_lead_time_min_days

            min_days = await _load_lead_time_min_days()
        except Exception:
            min_days = 3

        lead_window_start = (date.today() + timedelta(days=min_days)).isoformat()

        # Try cache first
        redis = _get_redis()
        cache_key = _build_cache_key(service_ids, audience, lead_window_start, days)
        slot_xml: str | None = None

        if redis is not None:
            try:
                cached = await redis.get(cache_key)
                if cached:
                    slot_xml = cached if isinstance(cached, str) else cached.decode()
                    logger.debug("AvailabilityContextMiddleware: cache hit for key %s", cache_key)
            except Exception as exc:
                logger.debug("AvailabilityContextMiddleware: cache get failed: %s", exc)

        if slot_xml is None:
            # Cache miss — fetch from service
            try:
                parsed_ids = [UUID(sid) for sid in service_ids]
            except (ValueError, TypeError):
                logger.warning(
                    "AvailabilityContextMiddleware: invalid service_ids, skipping: %s",
                    service_ids,
                )
                updated = _update_offered_slots_in_state(state, messages)
                req = request.override(state=updated) if updated is not state else request
                return await handler(req)

            try:
                window = await get_availability_window(
                    service_ids=parsed_ids,
                    audience=audience,
                    days=days,
                    max_slots_per_day=max_slots_per_day,
                )
            except Exception as exc:
                logger.warning(
                    "AvailabilityContextMiddleware: get_availability_window failed: %s", exc
                )
                updated = _update_offered_slots_in_state(state, messages)
                req = request.override(state=updated) if updated is not state else request
                return await handler(req)

            # Token-budget guard (ADR-3): too many day-lines → reduce window
            if _count_day_lines(window) > _MAX_DAY_LINES:
                try:
                    window = await get_availability_window(
                        service_ids=parsed_ids,
                        audience=audience,
                        days=5,
                        max_slots_per_day=2,
                    )
                except Exception:
                    pass  # Use original window if reduced call fails

            if not window:
                updated = _update_offered_slots_in_state(state, messages)
                req = request.override(state=updated) if updated is not state else request
                return await handler(req)

            slot_xml = _format_availability_xml(window)

            # Store in cache (best-effort)
            if redis is not None:
                try:
                    await redis.set(cache_key, slot_xml, ex=_CACHE_TTL)
                except Exception as exc:
                    logger.debug("AvailabilityContextMiddleware: cache set failed: %s", exc)

        new_state = {**state, "_slot_availability": slot_xml}
        logger.debug("AvailabilityContextMiddleware: injected _slot_availability")

        # J3: also materialize recently_offered_slots from ToolMessages
        new_state = _update_offered_slots_in_state(new_state, messages)
        return await handler(request.override(state=new_state))
