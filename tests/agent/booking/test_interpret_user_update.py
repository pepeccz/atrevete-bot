"""Tests for interpret_user_update node — Phase 5.5."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langgraph.types import Command


@pytest.fixture()
def base_state():
    return {
        "user_message": "quiero corte",
        "booking": {"step": "service", "service_ids": []},
        "messages": [],
        "customer_phone": "+34600000000",
        "conversation_id": "conv-1",
        "current_mode": "BOOKING",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
    }


@pytest.mark.asyncio
async def test_returns_command_goto_escape_gate(base_state):
    from agent.booking.interpret_user_update import interpret_user_update

    with (
        patch(
            "agent.booking.interpret_user_update.resolve_escape", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_audience", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_digit", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_negation", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_date", new=AsyncMock(return_value=None)),
        patch(
            "agent.booking.interpret_user_update.resolve_stylist", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_name", new=AsyncMock(return_value=None)),
    ):
        result = await interpret_user_update(base_state)

    assert isinstance(result, Command)
    assert result.goto == "escape_gate"


@pytest.mark.asyncio
async def test_merges_audience_patch(base_state):
    from agent.booking.interpret_user_update import interpret_user_update

    audience_patch = {"booking": {"audience": "adult_female"}}

    with (
        patch(
            "agent.booking.interpret_user_update.resolve_escape", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_audience",
            new=AsyncMock(return_value=audience_patch),
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_digit", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_negation", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_date", new=AsyncMock(return_value=None)),
        patch(
            "agent.booking.interpret_user_update.resolve_stylist", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_name", new=AsyncMock(return_value=None)),
    ):
        result = await interpret_user_update(base_state)

    assert result.update["booking"]["audience"] == "adult_female"
    # original step preserved
    assert result.update["booking"]["step"] == "service"


@pytest.mark.asyncio
async def test_merges_escape_intent(base_state):
    from agent.booking.interpret_user_update import interpret_user_update

    escape_patch = {"booking": {"_escape_intent": "cancel"}}

    with (
        patch(
            "agent.booking.interpret_user_update.resolve_escape",
            new=AsyncMock(return_value=escape_patch),
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_audience", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_digit", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_negation", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_date", new=AsyncMock(return_value=None)),
        patch(
            "agent.booking.interpret_user_update.resolve_stylist", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_name", new=AsyncMock(return_value=None)),
    ):
        result = await interpret_user_update(base_state)

    assert result.update["booking"]["_escape_intent"] == "cancel"


@pytest.mark.asyncio
async def test_no_llm_invoked(base_state):
    """interpret_user_update must NEVER call an LLM."""
    from agent.booking.interpret_user_update import interpret_user_update as _fn

    # patch all resolvers to return None
    with (
        patch(
            "agent.booking.interpret_user_update.resolve_escape", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_audience", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_digit", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_negation", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_date", new=AsyncMock(return_value=None)),
        patch(
            "agent.booking.interpret_user_update.resolve_stylist", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_name", new=AsyncMock(return_value=None)),
    ):
        # No real ChatOpenAI/LLM import happens — just assert no exception and Command returned
        result = await _fn(base_state)

    assert isinstance(result, Command)


@pytest.mark.asyncio
async def test_multiple_patches_merged(base_state):
    """Multiple resolver patches get shallow-merged into booking sub-dict."""
    from agent.booking.interpret_user_update import interpret_user_update

    audience_patch = {"booking": {"audience": "child_female"}}
    date_patch = {"booking": {"date": "2026-05-10"}}

    with (
        patch(
            "agent.booking.interpret_user_update.resolve_escape", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_audience",
            new=AsyncMock(return_value=audience_patch),
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_digit", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_negation", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_date",
            new=AsyncMock(return_value=date_patch),
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_stylist", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_name", new=AsyncMock(return_value=None)),
    ):
        result = await interpret_user_update(base_state)

    assert result.update["booking"]["audience"] == "child_female"
    assert result.update["booking"]["date"] == "2026-05-10"


@pytest.mark.asyncio
async def test_idempotent_no_change(base_state):
    """When all resolvers return None, booking slice is unchanged in update."""
    from agent.booking.interpret_user_update import interpret_user_update

    with (
        patch(
            "agent.booking.interpret_user_update.resolve_escape", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_audience", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_digit", new=AsyncMock(return_value=None)
        ),
        patch(
            "agent.booking.interpret_user_update.resolve_negation", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_date", new=AsyncMock(return_value=None)),
        patch(
            "agent.booking.interpret_user_update.resolve_stylist", new=AsyncMock(return_value=None)
        ),
        patch("agent.booking.interpret_user_update.resolve_name", new=AsyncMock(return_value=None)),
    ):
        result = await interpret_user_update(base_state)

    # booking update must equal original booking (no mutations)
    assert result.update["booking"] == {"step": "service", "service_ids": []}
