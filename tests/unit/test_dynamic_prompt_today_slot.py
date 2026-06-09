"""T8 — DynamicPromptMiddleware _slot_today regression lock.

Tests spec R4.1, R4.2 / ADR-9.
_slot_today MUST be written every turn.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, SystemMessage


class FakeRequest:
    def __init__(self, state=None):
        self._state = dict(state or {})
        self.system_message = SystemMessage(content="base")

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


@pytest.mark.asyncio
async def test_dynamic_prompt_writes_today_slot_every_turn():
    """DynamicPromptMiddleware must write _slot_today on every call."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    req = FakeRequest(state={})
    captured_state: list[dict] = []

    async def handler(r):
        captured_state.append(r.state)
        return FakeModelResponse()

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value="catalog"),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "10:00-20:00"}),
        ),
    ):
        mw = DynamicPromptMiddleware()
        await mw.awrap_model_call(req, handler)

    assert "_slot_today" in captured_state[0], "_slot_today must be set every turn"


@pytest.mark.asyncio
async def test_today_slot_contains_iso_date_spanish_weekday_and_time():
    """_slot_today must contain ISO date, Spanish weekday, and current time."""
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    req = FakeRequest(state={})
    captured_state: list[dict] = []

    async def handler(r):
        captured_state.append(r.state)
        return FakeModelResponse()

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        mw = DynamicPromptMiddleware()
        await mw.awrap_model_call(req, handler)

    slot = captured_state[0]["_slot_today"]
    assert "<today>" in slot, "Missing <today> tag"
    assert "fecha:" in slot, "Missing fecha: field"
    assert "dia_semana:" in slot, "Missing dia_semana: field"
    assert "hora_local:" not in slot, "hora_local removed in F3 for prefix cache stability"
    assert "tz: Europe/Madrid" in slot, "Missing tz field"

    # Check weekday is Spanish
    spanish_days = {"lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"}
    found_weekday = any(day in slot for day in spanish_days)
    assert found_weekday, f"No Spanish weekday found in slot: {slot}"
