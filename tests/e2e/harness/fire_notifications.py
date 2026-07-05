"""Fire one notifications-worker poll cycle in-process.

No real WhatsApp messages are delivered: the chatwoot send layer is replaced by a
capturing wrapper that records every send attempt and returns ``True`` so the handler
stamps the success timestamp exactly as production would.

Template names are resolved via the normal SettingsService / env-var fallback path,
but the cache is pre-seeded with test values before the cycle runs so an empty-string
DB setting never silently skips the send.

The ``auto_cancel`` handler does not send a WhatsApp message — its ``send_fn`` performs
a DB cancel directly.  The capturing wrapper calls the real ``send_fn`` (DB cancel
happens), records the result, and marks it without a ``skipped_reason``.  Set
``TEST_MODE_GCAL_SKIP=true`` to prevent real GCal calls during the cancel action.

Usage (must run with DB and Redis reachable on the target environment):
    export TEST_MODE_GCAL_SKIP=true
    export TEST_PHONE_PREFIX=+34999
    python tests/e2e/harness/fire_notifications.py \\
        --out tests/e2e/runs/<ts>/notifications_capture.json \\
        [--handlers reminder_24h confirm_48h]

    # Slice 3 handlers (require AUTO_CANCEL_ENABLED=true):
    export AUTO_CANCEL_ENABLED=true
    python tests/e2e/harness/fire_notifications.py \\
        --out tests/e2e/runs/<ts>/notifications_capture.json \\
        --handlers final_warning auto_cancel

Output JSON schema (written to --out):
    {
        "run_at": "<ISO 8601>",
        "handlers_fired": ["reminder_24h", ...],
        "send_attempts": [
            {
                "handler": "reminder_24h",
                "appointment_id": "<uuid>",
                "customer_phone": "+34999000001",
                "template_name": "test_reminder_24h",
                "body_params": {"1": "Ana", "2": "2026-07-01", "3": "10:00"},
                "category": "UTILITY",
                "language": "es",
                "conversation_id": 125,
                "success": true
            },
            ...
        ],
        "db_state": [
            {
                "appointment_id": "<uuid>",
                "reminder_sent_at": "<ISO>|null",
                "confirmation_sent_at": "<ISO>|null",
                "final_warning_sent_at": "<ISO>|null",
                "reminder_failed": false,
                "notification_failed": false,
                "status": "confirmed",
                "cancellation_reason": "<str>|null",
                "cancelled_at": "<ISO>|null"
            },
            ...
        ]
    }
"""

from __future__ import annotations

import os

# Must precede ALL shared.* imports — get_settings() is @lru_cache and reads env at first call.
# setdefault preserves any value the caller already set via the environment.
os.environ.setdefault("WHATSAPP_TEMPLATE_REMINDER_24H", "test_reminder_24h")
os.environ.setdefault("WHATSAPP_TEMPLATE_CONFIRM_48H", "test_confirm_48h")
os.environ.setdefault("WHATSAPP_TEMPLATE_FINAL_WARNING", "test_final_warning_handler")

import argparse
import asyncio
import dataclasses
import json
import logging
import pathlib
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Handler imports are safe after env vars are set — module-level code in the handlers
# only defines constants/dataclasses; get_settings() is called lazily inside send_fn.
from agent.workers.notification_handlers.auto_cancel import HANDLER as auto_cancel_handler
from agent.workers.notification_handlers.confirm_48h import HANDLER as confirm_48h_handler
from agent.workers.notification_handlers.final_warning import HANDLER as final_warning_handler
from agent.workers.notification_handlers.reminder_24h import HANDLER as reminder_24h_handler
from agent.workers.notifications_worker import process_handler

_ALL_HANDLERS = {
    "reminder_24h": reminder_24h_handler,
    "confirm_48h": confirm_48h_handler,
}
# Slice 3 handlers are only registered when AUTO_CANCEL_ENABLED is set — avoids making
# them part of the default --handlers list (and the default fire-all cycle) when the
# flag is off, which could unexpectedly cancel real appointments.
_AUTO_CANCEL_ENABLED = os.environ.get("AUTO_CANCEL_ENABLED", "").lower() in ("1", "true", "yes")
if _AUTO_CANCEL_ENABLED:
    _ALL_HANDLERS["final_warning"] = final_warning_handler
    _ALL_HANDLERS["auto_cancel"] = auto_cancel_handler

# Test template name defaults (used when env vars are absent).
_TEST_TEMPLATE_REMINDER = os.environ["WHATSAPP_TEMPLATE_REMINDER_24H"]
_TEST_TEMPLATE_CONFIRM = os.environ["WHATSAPP_TEMPLATE_CONFIRM_48H"]
_TEST_TEMPLATE_FINAL_WARNING = os.environ["WHATSAPP_TEMPLATE_FINAL_WARNING"]


async def _patch_settings_service() -> None:
    """Pre-populate SettingsService in-memory cache with test template names.

    This prevents an empty-string DB value from causing the handler's send_fn to
    skip the appointment (returning False → mark_failed instead of mark_sent).
    The cache entries are given a far-future expiry so they survive the whole cycle.
    """
    from datetime import datetime as _dt

    from shared.settings_service import get_settings_service

    svc = await get_settings_service()
    far_future = _dt(9999, 1, 1, tzinfo=UTC)
    async with svc._cache_lock:
        svc._cache["whatsapp_template_reminder_24h"] = {
            "value": _TEST_TEMPLATE_REMINDER,
            "expires_at": far_future,
        }
        svc._cache["whatsapp_template_confirm_48h"] = {
            "value": _TEST_TEMPLATE_CONFIRM,
            "expires_at": far_future,
        }
        svc._cache["whatsapp_template_final_warning"] = {
            "value": _TEST_TEMPLATE_FINAL_WARNING,
            "expires_at": far_future,
        }
    logger.debug(
        "Patched SettingsService cache: reminder=%r confirm=%r final_warning=%r",
        _TEST_TEMPLATE_REMINDER,
        _TEST_TEMPLATE_CONFIRM,
        _TEST_TEMPLATE_FINAL_WARNING,
    )


def _make_capturing_handler(handler, captures: list[dict[str, Any]]):
    """Return a new handler instance whose send_fn captures calls without HTTP.

    The capturing wrapper calls the ORIGINAL send_fn with a mock ChatwootClient.
    This exercises the full handler code path (SettingsService lookup, body_params
    construction, phone guard) while recording what would have been sent and
    returning True so process_handler calls mark_sent_fn.

    query_fn is also wrapped to eagerly load Appointment.customer before the query
    session closes.  Without this, the no-chatwoot path (e.g. auto_cancel) raises
    DetachedInstanceError when capturing_send_fn accesses appt.customer.phone after
    the query session has already been torn down by process_handler.
    """
    original_query_fn = handler.query_fn
    original_send_fn = handler.send_fn

    async def capturing_query_fn(session: Any) -> list:
        """Re-fetch base results with selectinload(customer) in the same open session."""
        from sqlalchemy import select as _select
        from sqlalchemy.orm import selectinload as _selectinload

        from database.models import Appointment as _Appointment

        base = await original_query_fn(session)
        if not base:
            return base
        ids = [a.id for a in base]
        refreshed = await session.execute(
            _select(_Appointment)
            .options(_selectinload(_Appointment.customer))
            .where(_Appointment.id.in_(ids))
        )
        return list(refreshed.scalars().all())

    async def capturing_send_fn(appt: Any, _ignored_client: Any) -> bool:
        call_record: dict[str, Any] = {}

        class _CapturingClient:
            async def send_template_message(
                self,
                customer_phone: str,
                template_name: str,
                body_params: dict[str, str],
                category: str = "UTILITY",
                language: str = "es",
                conversation_id: int | None = None,
                **_kw: Any,
            ) -> bool:
                call_record["customer_phone"] = customer_phone
                call_record["template_name"] = template_name
                call_record["body_params"] = body_params
                call_record["category"] = category
                call_record["language"] = language
                # sdd/context-coherence TASK-21: capture conversation_id (previously
                # swallowed via **_kw) so the QA scenario can assert threading —
                # deliver_template() passes conversation_id=int(history.conversation_id)
                # when the customer has a resolvable canonical conversation.
                call_record["conversation_id"] = conversation_id
                return True

            async def create_conversation_with_template(
                self,
                customer_phone: str,
                template_name: str,
                body_params: dict[str, str],
                category: str = "UTILITY",
                language: str = "es",
                **_kw: Any,
            ) -> tuple[int | None, bool]:
                # Fallback path (resolver miss / rejected conversation_id, D3). No new
                # conversation is created for real — return a sentinel id so
                # deliver_template's success path completes without a live Chatwoot call.
                call_record["customer_phone"] = customer_phone
                call_record["template_name"] = template_name
                call_record["body_params"] = body_params
                call_record["category"] = category
                call_record["language"] = language
                call_record["conversation_id"] = None
                call_record["fallback_conversation_created"] = True
                return -1, True

        result = await original_send_fn(appt, _CapturingClient())

        if call_record:
            # Normal path: send_fn resolved the template and called chatwoot.
            captures.append(
                {
                    "handler": handler.name,
                    "appointment_id": str(appt.id),
                    "customer_phone": call_record.get("customer_phone"),
                    "template_name": call_record.get("template_name"),
                    "body_params": call_record.get("body_params"),
                    "category": call_record.get("category"),
                    "language": call_record.get("language"),
                    "conversation_id": call_record.get("conversation_id"),
                    "success": result,
                }
            )
        else:
            # send_fn did not invoke chatwoot (empty template, no phone, or DB-action
            # handler such as auto_cancel).  Use the real return value — a DB-action
            # handler may return True even with no chatwoot call.
            entry: dict[str, Any] = {
                "handler": handler.name,
                "appointment_id": str(appt.id),
                "customer_phone": (
                    getattr(appt.customer, "phone", None) if appt.customer else None
                ),
                "template_name": None,
                "body_params": None,
                "category": None,
                "language": None,
                "conversation_id": None,
                "success": result,
            }
            if not result:
                entry["skipped_reason"] = "empty_template_or_no_phone"
            captures.append(entry)

        return result

    return dataclasses.replace(handler, query_fn=capturing_query_fn, send_fn=capturing_send_fn)


async def _query_db_state(appointment_ids: list[str]) -> list[dict[str, Any]]:
    """Return post-run DB fields for the given appointment UUIDs."""
    if not appointment_ids:
        return []

    from sqlalchemy import select

    from database.connection import get_async_session
    from database.models import Appointment

    uuids = [UUID(aid) for aid in appointment_ids]
    async with get_async_session() as session:
        stmt = select(Appointment).where(Appointment.id.in_(uuids))
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    return [
        {
            "appointment_id": str(row.id),
            "reminder_sent_at": row.reminder_sent_at.isoformat() if row.reminder_sent_at else None,
            "confirmation_sent_at": (
                row.confirmation_sent_at.isoformat() if row.confirmation_sent_at else None
            ),
            "final_warning_sent_at": (
                row.final_warning_sent_at.isoformat() if row.final_warning_sent_at else None
            ),
            "reminder_failed": row.reminder_failed,
            "notification_failed": row.notification_failed,
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "cancellation_reason": row.cancellation_reason,
            "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        }
        for row in rows
    ]


async def run_cycle(handler_names: list[str]) -> dict[str, Any]:
    """Run one poll cycle for the requested handlers.

    Patches SettingsService, wraps each handler with a capturing send_fn,
    invokes process_handler (the real worker logic), then queries DB for
    post-run state.

    Returns:
        Full capture dict matching the schema documented in the module docstring.
    """
    await _patch_settings_service()

    captures: list[dict[str, Any]] = []
    handlers_fired: list[str] = []

    # Null client passed to process_handler — our capturing wrapper never calls it.
    class _NullClient:
        pass

    for name in handler_names:
        handler = _ALL_HANDLERS.get(name)
        if handler is None:
            raise ValueError(f"Unknown handler: {name!r}. Valid: {sorted(_ALL_HANDLERS)}")
        wrapped = _make_capturing_handler(handler, captures)
        await process_handler(wrapped, _NullClient())  # type: ignore[arg-type]
        handlers_fired.append(name)

    appointment_ids = [c["appointment_id"] for c in captures if c.get("appointment_id")]
    db_state = await _query_db_state(appointment_ids)

    return {
        "run_at": datetime.now(UTC).isoformat(),
        "handlers_fired": handlers_fired,
        "send_attempts": captures,
        "db_state": db_state,
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(
        description=(
            "Fire one notifications-worker poll cycle in-process. "
            "No real WhatsApp messages are sent. Writes a capture JSON to --out."
        )
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to write the capture JSON output.",
    )
    parser.add_argument(
        "--handlers",
        nargs="+",
        default=list(_ALL_HANDLERS),
        choices=list(_ALL_HANDLERS),
        metavar="HANDLER",
        help=f"Which handlers to fire. Default: all ({', '.join(_ALL_HANDLERS)}).",
    )
    args = parser.parse_args()

    result = asyncio.run(run_cycle(args.handlers))

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    summary = {
        "ok": True,
        "out": str(out_path),
        "handlers_fired": result["handlers_fired"],
        "send_attempts": len(result["send_attempts"]),
        "db_state_rows": len(result["db_state"]),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
