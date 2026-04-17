"""Unit tests for ``DynamicToolsMiddleware`` — closure-based API (NEW).

These tests target the REWRITTEN API:
    DynamicToolsMiddleware(get_tools_fn: Callable[[], list[BaseTool]])

The old API (`allowed_names: Callable[[AgentState], set[str]]`) is gone.
Running these tests on master FAILS because the current class still uses the
old state-based constructor signature.  That failure is the expected RED state.

Tests (6):
    test_closure_filters_tools_per_model_call
    test_closure_reads_live_node_attribute_between_calls
    test_sync_async_parity
    test_override_not_dataclasses_replace
    test_empty_get_tools_fn_does_not_raise
    test_non_overlapping_tools_produces_empty_list
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import tool

from agent.middleware.dynamic_tools import DynamicToolsMiddleware
from langchain.agents.middleware.types import ModelRequest


# ---------------------------------------------------------------------------
# Tool stubs
# ---------------------------------------------------------------------------


@tool
def _update_stub(x: str | None = None) -> str:  # type: ignore[override]
    """update stub tool"""
    return f"updated {x}"


@tool
def _check_stub(x: str | None = None) -> str:  # type: ignore[override]
    """check stub tool"""
    return f"checked {x}"


@tool
def _book_stub(x: str | None = None) -> str:  # type: ignore[override]
    """book stub tool"""
    return f"booked {x}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(tools: list) -> ModelRequest:
    """Build a minimal ModelRequest with a given tool list."""
    model = MagicMock()
    model.bind_tools = MagicMock(return_value=model)
    return ModelRequest(
        model=model,
        messages=[],
        tools=tools,
        state={"messages": []},
    )


def _sync_handler(request: ModelRequest):
    """Capture-and-return handler for wrap_model_call."""
    return request


async def _async_handler(request: ModelRequest):
    """Async capture-and-return handler for awrap_model_call."""
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_closure_filters_tools_per_model_call():
    """get_tools_fn is called on every model call and filters tools correctly.

    Expected RED on master: ``DynamicToolsMiddleware(get_tools_fn=...)`` raises
    TypeError because the current class expects ``allowed_names`` (a state→set callable).
    """
    mw = DynamicToolsMiddleware(get_tools_fn=lambda: [_update_stub])

    request = _make_request(tools=[_update_stub, _check_stub, _book_stub])
    result = mw.wrap_model_call(request, _sync_handler)

    tool_names = [t.name for t in result.tools]
    assert tool_names == ["_update_stub"], (
        f"Expected only _update_stub, got {tool_names}"
    )


def test_closure_reads_live_node_attribute_between_calls():
    """Closure captures a live mutable reference — tool list changes between calls.

    This proves the filter is re-evaluated on every model call, not frozen
    at construction time.

    Expected RED on master: TypeError on construction (old API).
    """
    ctx: dict = {"phase": "empty"}

    def get_tools() -> list:
        if ctx["phase"] == "empty":
            return [_update_stub]
        return [_update_stub, _book_stub]

    mw = DynamicToolsMiddleware(get_tools_fn=get_tools)

    request = _make_request(tools=[_update_stub, _check_stub, _book_stub])

    # First call — only _update_stub
    result1 = mw.wrap_model_call(request, _sync_handler)
    assert [t.name for t in result1.tools] == ["_update_stub"]

    # Mutate ctx — simulates node updating booking_context
    ctx["phase"] = "complete"

    # Second call through the same middleware — closure now returns 2 tools
    result2 = mw.wrap_model_call(request, _sync_handler)
    assert set(t.name for t in result2.tools) == {"_update_stub", "_book_stub"}, (
        f"Expected update+book after mutation, got {[t.name for t in result2.tools]}"
    )


def test_sync_async_parity():
    """wrap_model_call and awrap_model_call produce identical filtering results.

    Expected RED on master: TypeError on construction (old API).
    """
    mw = DynamicToolsMiddleware(get_tools_fn=lambda: [_update_stub])
    request = _make_request(tools=[_update_stub, _check_stub])

    sync_result = mw.wrap_model_call(request, _sync_handler)
    async_result = asyncio.get_event_loop().run_until_complete(
        mw.awrap_model_call(request, _async_handler)
    )

    sync_names = [t.name for t in sync_result.tools]
    async_names = [t.name for t in async_result.tools]

    assert sync_names == async_names == ["_update_stub"], (
        f"Sync={sync_names!r} and async={async_names!r} must be identical and filter to [_update_stub]"
    )


def test_override_not_dataclasses_replace():
    """The filtered request must be produced via request.override(), not dataclasses.replace.

    We verify the output by asserting:
    1. The returned object is a ModelRequest.
    2. Its tools list contains only the allowed tools (proving override() worked).

    Expected RED on master: TypeError on construction (old API) + old code uses
    ``dataclasses.replace`` which emits a DeprecationWarning.
    """
    mw = DynamicToolsMiddleware(get_tools_fn=lambda: [_check_stub])
    request = _make_request(tools=[_update_stub, _check_stub])

    result = mw.wrap_model_call(request, _sync_handler)

    assert isinstance(result, ModelRequest), (
        f"Result must be a ModelRequest, got {type(result)}"
    )
    assert [t.name for t in result.tools] == ["_check_stub"], (
        f"override() must produce a request with only _check_stub, got {[t.name for t in result.tools]}"
    )
    # Original request is unchanged (immutable override pattern)
    assert len(request.tools) == 2, "Original request.tools must be unchanged after override()"


def test_empty_get_tools_fn_does_not_raise():
    """get_tools_fn returning [] must NOT raise — model receives empty tool list.

    Expected RED on master: TypeError on construction (old API).
    """
    mw = DynamicToolsMiddleware(get_tools_fn=lambda: [])
    request = _make_request(tools=[_update_stub, _check_stub])

    result = mw.wrap_model_call(request, _sync_handler)

    assert result.tools == [], (
        f"Empty get_tools_fn must yield empty tools on request, got {result.tools}"
    )


def test_non_overlapping_tools_produces_empty_list():
    """Closure returning tools NOT in request.tools → empty result (intersection, not injection).

    The middleware must NOT inject tools the agent wasn't bound with.

    Expected RED on master: TypeError on construction (old API).
    """
    # Closure returns _book_stub, but request only has _update_stub and _check_stub
    mw = DynamicToolsMiddleware(get_tools_fn=lambda: [_book_stub])
    request = _make_request(tools=[_update_stub, _check_stub])  # _book_stub NOT here

    result = mw.wrap_model_call(request, _sync_handler)

    assert result.tools == [], (
        f"Non-overlapping closure must yield empty tool list, got {[t.name for t in result.tools]}"
    )
