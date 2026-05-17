"""T6 — AvailabilityContextMiddleware tests.

Tests spec R1.1–R1.5, R1.7 / ADR-1, ADR-3, ADR-4, ADR-5.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, SystemMessage

# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------

SERVICE_ID = str(uuid4())
STYLIST_ID = str(uuid4())


class FakeRequest:
    def __init__(self, state=None, system_content="base"):
        self._state = dict(state or {})
        self.system_message = SystemMessage(content=system_content)

    @property
    def state(self):
        return self._state

    def override(self, **kwargs):
        new = FakeRequest(state=kwargs.get("state", self._state))
        new.system_message = kwargs.get("system_message", self.system_message)
        return new


class FakeModelResponse:
    def __init__(self):
        self.result = [AIMessage(content="ok")]
        self.structured_response = None


def _make_update_booking_msg(service_ids=None):
    """Build a fake update_booking ToolMessage with service_ids in payload."""
    msg = MagicMock()
    msg.name = "update_booking"
    msg.content = json.dumps({
        "status": "partial",
        "collected": {
            "service_ids": service_ids or [SERVICE_ID],
        },
    })
    return msg


FAKE_WINDOW = {
    "Pilar": [
        {"date_iso": "2026-04-30", "weekday_es": "jueves", "slots": ["10:00", "11:00"]},
    ]
}

FAKE_AVAILABILITY_XML = (
    "<availability>\n"
    "## Próximos huecos\nPilar\n  jueves 30 abril (2026-04-30): 10:00, 11:00\n"
    "</availability>"
)


# ---------------------------------------------------------------------------
# T6.1 — No injection when no service_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_injection_when_no_service_ids():
    """No update_booking ToolMessage → _slot_availability not set."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    req = FakeRequest(state={"messages": []})
    captured_state: list[dict] = []

    async def handler(r):
        captured_state.append(r.state)
        return FakeModelResponse()

    mw = AvailabilityContextMiddleware()
    await mw.awrap_model_call(req, handler)

    assert "_slot_availability" not in captured_state[0]


# ---------------------------------------------------------------------------
# T6.2 — Injection when service_ids present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_injection_when_service_ids_present():
    """ToolMessage with service_ids → get_availability_window called → _slot_availability set."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    msg = _make_update_booking_msg(service_ids=[SERVICE_ID])
    req = FakeRequest(state={"messages": [msg]})
    captured_state: list[dict] = []

    async def handler(r):
        captured_state.append(r.state)
        return FakeModelResponse()

    with (
        patch(
            "agent.middleware.availability_context.get_availability_window",
            new=AsyncMock(return_value=FAKE_WINDOW),
        ),
        patch(
            "agent.middleware.availability_context._get_redis",
            return_value=None,  # no cache
        ),
    ):
        mw = AvailabilityContextMiddleware()
        await mw.awrap_model_call(req, handler)

    assert "_slot_availability" in captured_state[0]
    slot = captured_state[0]["_slot_availability"]
    assert "<availability>" in slot
    assert "Pilar" in slot


# ---------------------------------------------------------------------------
# T6.3 — Cache hit skips service call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_service_call():
    """Second call within TTL → get_availability_window NOT called again."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    msg = _make_update_booking_msg(service_ids=[SERVICE_ID])
    req = FakeRequest(state={"messages": [msg]})

    fake_redis = AsyncMock()
    fake_redis.get = AsyncMock(return_value=FAKE_AVAILABILITY_XML)
    fake_redis.set = AsyncMock()

    mock_window = AsyncMock(return_value=FAKE_WINDOW)

    with (
        patch(
            "agent.middleware.availability_context.get_availability_window",
            new=mock_window,
        ),
        patch(
            "agent.middleware.availability_context._get_redis",
            return_value=fake_redis,
        ),
    ):
        mw = AvailabilityContextMiddleware()

        async def handler(r):
            return FakeModelResponse()

        await mw.awrap_model_call(req, handler)

    # Service should NOT have been called because cache returned a value
    mock_window.assert_not_called()


# ---------------------------------------------------------------------------
# T6.4 — Cache miss calls service and caches result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_calls_service():
    """Cache miss → get_availability_window called; result stored in cache."""
    from agent.middleware.availability_context import AvailabilityContextMiddleware

    msg = _make_update_booking_msg(service_ids=[SERVICE_ID])
    req = FakeRequest(state={"messages": [msg]})

    fake_redis = AsyncMock()
    fake_redis.get = AsyncMock(return_value=None)  # cache miss
    fake_redis.set = AsyncMock()

    mock_window = AsyncMock(return_value=FAKE_WINDOW)

    with (
        patch(
            "agent.middleware.availability_context.get_availability_window",
            new=mock_window,
        ),
        patch(
            "agent.middleware.availability_context._get_redis",
            return_value=fake_redis,
        ),
    ):
        mw = AvailabilityContextMiddleware()

        async def handler(r):
            return FakeModelResponse()

        await mw.awrap_model_call(req, handler)

    mock_window.assert_called_once()
    # Redis set should have been called to store result
    fake_redis.set.assert_called_once()
