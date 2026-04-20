"""Regression tests for ``_invoke_create_agent`` exception path in BOOKING
and APPOINTMENT_MANAGEMENT modes.

Before the fix, when ``create_agent.ainvoke`` raised (e.g. because
``NodeBridgeMiddleware`` exposed only an async hook that LangChain 1.2.x
could not detect), the except branch returned ``AgenticLoopResult(
response_text="", error=str(exc))``. The intro prefixer then produced a
user-visible silent failure.

After the fix the except branch MUST return ``response_text=fallback_text``
so the user sees a coherent recovery message and the error still flows to
logs via the ``error`` field.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# BookingModeNode — exception branch returns fallback_text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_booking_invoke_create_agent_exception_returns_fallback_not_empty() -> None:
    from agent.modes.booking_mode import BookingModeNode

    # Build a node with minimal init (tools=[], no LLM) — we only drive one method.
    node = BookingModeNode.__new__(BookingModeNode)
    node.tools = []
    node.llm = MagicMock()  # never called — create_agent is mocked below

    class _AsyncRaiser:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("boom")

    def _fake_create_agent(*args, **kwargs):
        return _AsyncRaiser()

    with patch("agent.modes.booking_mode.create_agent", side_effect=_fake_create_agent):
        result = await node._invoke_create_agent(
            messages=[], tools=[], tool_choice=None
        )

    fallback_text = "Perdona, tuve un problema procesando tu mensaje. ¿Puedes repetirlo?"
    assert result.response_text == fallback_text
    assert result.response_text != ""
    assert result.error == "boom"


# ---------------------------------------------------------------------------
# AppointmentManagementMode — exception branch returns fallback_text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appointment_mgmt_invoke_create_agent_exception_returns_fallback_not_empty() -> None:
    from agent.modes.appointment_management_mode import AppointmentManagementMode

    node = AppointmentManagementMode.__new__(AppointmentManagementMode)
    node.tools = []
    node.llm = MagicMock()

    class _AsyncRaiser:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("kaboom")

    def _fake_create_agent(*args, **kwargs):
        return _AsyncRaiser()

    with patch("langchain.agents.create_agent", side_effect=_fake_create_agent):
        result = await node._invoke_create_agent(messages=[], tools=[])

    fallback_text = "Perdona, tuve un problema procesando tu mensaje. ¿Puedes repetirlo?"
    assert result.response_text == fallback_text
    assert result.response_text != ""
    assert result.error == "kaboom"
