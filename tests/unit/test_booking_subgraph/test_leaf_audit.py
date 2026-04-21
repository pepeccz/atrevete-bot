"""
Phase 6 — Leaf audit + _last_leaf tests (INV-2, D5, D8).

Each leaf with mocked LLM response that injects extra key → assert guard raises.
Normal return passes. Each leaf writes _last_leaf in booking_context.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage


def _make_mock_llm(content: str = "respuesta") -> AsyncMock:
    mock = AsyncMock()
    mock.ainvoke.return_value = AIMessage(content=content)
    return mock


def _state(bc: dict | None = None) -> dict:
    return {
        "booking_context": bc or {},
        "messages": [],
        "user_message": "hola",
        "total_message_count": 0,
    }


# ---------------------------------------------------------------------------
# _assert_leaf_pure guard
# ---------------------------------------------------------------------------


def test_assert_leaf_pure_raises_on_extra_key():
    from agent.booking.nodes.leaf_llm import _assert_leaf_pure

    with pytest.raises(AssertionError, match="leaf must not mutate state"):
        # "current_mode" is not an allowed key — only messages/total_message_count/booking_context
        _assert_leaf_pure({"messages": [], "current_mode": "BOOKING"})


def test_assert_leaf_pure_passes_on_allowed_keys():
    from agent.booking.nodes.leaf_llm import _assert_leaf_pure

    # Should not raise
    _assert_leaf_pure({"messages": [], "total_message_count": 1})


def test_assert_leaf_pure_passes_empty():
    from agent.booking.nodes.leaf_llm import _assert_leaf_pure

    _assert_leaf_pure({})


# ---------------------------------------------------------------------------
# _last_leaf written by leaves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_service_writes_last_leaf():
    from agent.booking.nodes.leaf_llm import ask_service

    with patch("agent.booking.nodes.leaf_llm.llm", _make_mock_llm()):
        result = await ask_service(_state())

    # ask_service should write _last_leaf via booking_context update
    bc_update = result.get("booking_context") or {}
    assert bc_update.get("_last_leaf") == "ask_service"


@pytest.mark.asyncio
async def test_ask_name_writes_last_leaf():
    from agent.booking.nodes.leaf_llm import ask_name

    with patch("agent.booking.nodes.leaf_llm.llm", _make_mock_llm()):
        result = await ask_name(_state())

    bc_update = result.get("booking_context") or {}
    assert bc_update.get("_last_leaf") == "ask_name"


@pytest.mark.asyncio
async def test_ask_notes_writes_last_leaf():
    from agent.booking.nodes.leaf_llm import ask_notes

    with patch("agent.booking.nodes.leaf_llm.llm", _make_mock_llm()):
        result = await ask_notes(_state())

    bc_update = result.get("booking_context") or {}
    assert bc_update.get("_last_leaf") == "ask_notes"


@pytest.mark.asyncio
async def test_ask_more_services_writes_last_leaf():
    from agent.booking.nodes.leaf_llm import ask_more_services

    with patch("agent.booking.nodes.leaf_llm.llm", _make_mock_llm()):
        result = await ask_more_services(_state())

    bc_update = result.get("booking_context") or {}
    assert bc_update.get("_last_leaf") == "ask_more_services"
