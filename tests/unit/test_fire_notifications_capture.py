"""Unit tests for tests/e2e/harness/fire_notifications.py — TASK-21 (sdd/context-coherence).

Covers the ``_CapturingClient`` enhancement: ``conversation_id`` is captured instead
of being swallowed via ``**_kw``, and a stubbed ``create_conversation_with_template``
keeps the capturing path working now that ``deliver_template`` may call it on the
fallback branch (resolver-miss or Chatwoot rejection).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "e2e" / "harness"))

from fire_notifications import _make_capturing_handler  # noqa: E402

from agent.workers.notification_handlers.base import NotificationHandler  # noqa: E402


def _make_appt() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), customer=SimpleNamespace(phone="+34999000001"))


@pytest.mark.asyncio
async def test_capturing_client_records_conversation_id_on_existing_conversation_send():
    async def fake_send_fn(appt, client) -> bool:
        return await client.send_template_message(
            customer_phone=appt.customer.phone,
            template_name="appointment_confirmation_48h",
            body_params={"1": "Ana"},
            category="UTILITY",
            language="es",
            conversation_id=125,
            fallback_content="Hola Ana",
        )

    async def fake_query_fn(session):
        return []

    handler = NotificationHandler(
        name="confirm_48h",
        query_fn=fake_query_fn,
        send_fn=fake_send_fn,
        mark_sent_fn=fake_query_fn,
        mark_failed_fn=fake_query_fn,
    )
    captures: list[dict] = []
    wrapped = _make_capturing_handler(handler, captures)

    appt = _make_appt()
    result = await wrapped.send_fn(appt, None)

    assert result is True
    assert len(captures) == 1
    assert captures[0]["conversation_id"] == 125
    assert captures[0]["handler"] == "confirm_48h"


@pytest.mark.asyncio
async def test_capturing_client_supports_fallback_create_conversation():
    async def fake_send_fn(appt, client) -> bool:
        new_id, success = await client.create_conversation_with_template(
            customer_phone=appt.customer.phone,
            template_name="appointment_confirmation_48h",
            body_params={"1": "Ana"},
            category="UTILITY",
            language="es",
            fallback_content="Hola Ana",
        )
        return success

    async def fake_query_fn(session):
        return []

    handler = NotificationHandler(
        name="confirm_48h",
        query_fn=fake_query_fn,
        send_fn=fake_send_fn,
        mark_sent_fn=fake_query_fn,
        mark_failed_fn=fake_query_fn,
    )
    captures: list[dict] = []
    wrapped = _make_capturing_handler(handler, captures)

    appt = _make_appt()
    result = await wrapped.send_fn(appt, None)

    assert result is True
    assert len(captures) == 1
    # Fallback path never resolves a real conversation_id — must not be confused
    # with an existing-conversation send.
    assert captures[0]["conversation_id"] is None


@pytest.mark.asyncio
async def test_fallback_create_returns_unique_sentinel_ids_across_calls():
    """FIX 4 (sdd/context-coherence, both judges MAJOR): a fixed sentinel id
    (-1) previously collided across every fallback-create call in a batch,
    silently corrupting harness signals via the ConversationHistory unique
    constraint. Each call must draw a distinct negative id."""

    async def fake_send_fn(appt, client) -> bool:
        new_id, success = await client.create_conversation_with_template(
            customer_phone=appt.customer.phone,
            template_name="appointment_confirmation_48h",
            body_params={"1": "Ana"},
            category="UTILITY",
            language="es",
            fallback_content="Hola Ana",
        )
        assert success is True
        return new_id

    async def fake_query_fn(session):
        return []

    handler = NotificationHandler(
        name="confirm_48h",
        query_fn=fake_query_fn,
        send_fn=fake_send_fn,
        mark_sent_fn=fake_query_fn,
        mark_failed_fn=fake_query_fn,
    )
    captures: list[dict] = []
    wrapped = _make_capturing_handler(handler, captures)

    sentinel_ids = [await wrapped.send_fn(_make_appt(), None) for _ in range(5)]

    assert len(sentinel_ids) == len(set(sentinel_ids)), "sentinel ids must be unique per call"
    assert all(isinstance(sid, int) and sid < 0 for sid in sentinel_ids)
