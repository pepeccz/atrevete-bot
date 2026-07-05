"""Pins the number of WhatsApp template body params per notification handler.

sdd/context-coherence FIX 6: docs/whatsapp-templates.md previously documented 3
positional variables for both confirm_48h and reminder_24h, but the live code
sends 6 and 4 respectively (Madrid/Spanish rendering + stylist/service/deadline
enrichment). A 2026-07-05 forced send confirmed Meta's live templates accept
these counts, so the docs (not the code) were stale — see the updated doc note
and engram #7493. This test fails loudly if a future change silently drifts
the param count away from what's documented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

# Documented param counts (docs/whatsapp-templates.md sections 1.1 / 1.2).
CONFIRM_48H_PARAM_COUNT = 6
REMINDER_24H_PARAM_COUNT = 4
FINAL_WARNING_PARAM_COUNT = 3


class _DummyAutoCancelSettings:
    AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS = 12
    AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS = 6


@pytest.mark.asyncio
async def test_confirm_48h_body_params_count_matches_documented():
    from agent.workers.notification_handlers import confirm_48h

    appt = SimpleNamespace(
        id=uuid4(),
        first_name="Ana",
        stylist_id=None,
        service_ids=[],
        start_time=datetime(2026, 7, 9, 12, 30, tzinfo=UTC),
    )

    params = await confirm_48h._build_body_params(appt, _DummyAutoCancelSettings())

    assert len(params) == CONFIRM_48H_PARAM_COUNT
    assert set(params.keys()) == {str(i) for i in range(1, CONFIRM_48H_PARAM_COUNT + 1)}


@pytest.mark.asyncio
async def test_reminder_24h_body_params_count_matches_documented():
    from agent.workers.notification_handlers import reminder_24h

    appt = SimpleNamespace(
        id=uuid4(),
        first_name="Ana",
        service_ids=[],
        start_time=datetime(2026, 7, 9, 12, 30, tzinfo=UTC),
    )

    params = await reminder_24h._build_body_params(appt)

    assert len(params) == REMINDER_24H_PARAM_COUNT
    assert set(params.keys()) == {str(i) for i in range(1, REMINDER_24H_PARAM_COUNT + 1)}


def test_final_warning_body_params_count_matches_documented():
    from agent.workers.notification_handlers import final_warning

    appt = SimpleNamespace(
        id=uuid4(),
        first_name="Ana",
        start_time=datetime(2026, 7, 9, 12, 30, tzinfo=UTC),
    )

    params = final_warning._build_body_params(appt)

    assert len(params) == FINAL_WARNING_PARAM_COUNT
    assert set(params.keys()) == {str(i) for i in range(1, FINAL_WARNING_PARAM_COUNT + 1)}
