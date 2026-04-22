"""Tests for ToolVisibilityMiddleware — Phase 5.4."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool


def _make_tool(name: str) -> MagicMock:
    t = MagicMock(spec=BaseTool)
    t.name = name
    return t


class _FakeModelResponse:
    def __init__(self):
        self.result = [AIMessage(content="ok")]
        self.structured_response = None


def _make_request(step: str | None, tools: list) -> MagicMock:
    state = {"booking": {"step": step} if step is not None else None}
    req = MagicMock()
    req.state = state
    req.tools = tools
    req.system_message = SystemMessage(content="base")

    def override(**kwargs):
        new = MagicMock()
        new.state = req.state
        new.tools = kwargs.get("tools", req.tools)
        new.system_message = req.system_message
        return new

    req.override = override
    return req


@pytest.mark.asyncio
async def test_step_confirm_exposes_only_book():
    from agent.middleware.tool_visibility import ToolVisibilityMiddleware

    book_tool = _make_tool("book")
    check_tool = _make_tool("check_availability")
    query_tool = _make_tool("query_info")

    all_tools = [book_tool, check_tool, query_tool]
    req = _make_request("confirm", all_tools)

    captured = []

    async def handler(r):
        captured.append(r)
        return _FakeModelResponse()

    mw = ToolVisibilityMiddleware(all_tools)
    await mw.awrap_model_call(req, handler)

    passed_tools = [t.name for t in captured[0].tools]
    assert passed_tools == ["book"]


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["date", "slot"])
async def test_date_slot_step_exposes_check_availability(step):
    from agent.middleware.tool_visibility import ToolVisibilityMiddleware

    book_tool = _make_tool("book")
    check_tool = _make_tool("check_availability")
    query_tool = _make_tool("query_info")

    all_tools = [book_tool, check_tool, query_tool]
    req = _make_request(step, all_tools)

    captured = []

    async def handler(r):
        captured.append(r)
        return _FakeModelResponse()

    mw = ToolVisibilityMiddleware(all_tools)
    await mw.awrap_model_call(req, handler)

    passed_tools = [t.name for t in captured[0].tools]
    assert "check_availability" in passed_tools
    assert "book" not in passed_tools


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["service", "audience", "stylist", "name", "notes"])
async def test_other_steps_expose_no_tools(step):
    from agent.middleware.tool_visibility import ToolVisibilityMiddleware

    all_tools = [_make_tool("book"), _make_tool("check_availability"), _make_tool("query_info")]
    req = _make_request(step, all_tools)

    captured = []

    async def handler(r):
        captured.append(r)
        return _FakeModelResponse()

    mw = ToolVisibilityMiddleware(all_tools)
    await mw.awrap_model_call(req, handler)

    assert captured[0].tools == []


@pytest.mark.asyncio
async def test_no_booking_state_exposes_no_booking_tools():
    """When booking is None (general mode), no booking-specific tools exposed."""
    from agent.middleware.tool_visibility import ToolVisibilityMiddleware

    all_tools = [_make_tool("book"), _make_tool("check_availability"), _make_tool("query_info")]
    req = _make_request(None, all_tools)

    captured = []

    async def handler(r):
        captured.append(r)
        return _FakeModelResponse()

    mw = ToolVisibilityMiddleware(all_tools)
    await mw.awrap_model_call(req, handler)

    # with no booking step, no booking tools exposed
    passed_tool_names = [t.name for t in captured[0].tools]
    assert "book" not in passed_tool_names
    assert "check_availability" not in passed_tool_names
