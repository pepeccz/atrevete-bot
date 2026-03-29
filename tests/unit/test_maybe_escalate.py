"""Unit tests for _maybe_escalate() graph helper.

NOTE: perform_escalation is imported lazily inside _maybe_escalate() using a
local `from agent.services.escalation_service import perform_escalation`.
We patch it at its source module so the lazy import picks up the mock.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agent.graphs.conversation_flow import _maybe_escalate
from agent.services.escalation_service import EscalationResult

# Patch target: the function at its definition site
_PATCH_TARGET = "agent.services.escalation_service.perform_escalation"


@pytest.fixture
def mock_escalation_result():
    return EscalationResult(
        success=True,
        steps_completed=["disable_bot", "labels", "private_note", "db_record"],
        user_message="Te paso con alguien del equipo. 🙏",
    )


@pytest.mark.asyncio
async def test_maybe_escalate_triggered(mock_escalation_result):
    """Calls perform_escalation when escalation_triggered=True in node_result."""
    state = {
        "conversation_id": "123",
        "customer_phone": "+5491100000000",
        "escalation_triggered": False,
        "error_count": 0,
    }
    node_result = {
        "escalation_triggered": True,
    }
    with patch(_PATCH_TARGET, AsyncMock(return_value=mock_escalation_result)) as mock_esc:
        result = await _maybe_escalate(node_result, state)
    mock_esc.assert_called_once()
    assert result.get("_escalation_performed") is True


@pytest.mark.asyncio
async def test_maybe_escalate_triggered_from_state(mock_escalation_result):
    """Calls perform_escalation when escalation_triggered=True in state."""
    state = {
        "conversation_id": "123",
        "customer_phone": "+5491100000000",
        "escalation_triggered": True,
        "error_count": 0,
    }
    node_result = {}
    with patch(_PATCH_TARGET, AsyncMock(return_value=mock_escalation_result)) as mock_esc:
        result = await _maybe_escalate(node_result, state)
    mock_esc.assert_called_once()
    assert result.get("_escalation_performed") is True


@pytest.mark.asyncio
async def test_maybe_escalate_not_triggered():
    """Does NOT call perform_escalation when no trigger and error_count < 3."""
    state = {"conversation_id": "123", "error_count": 0}
    node_result = {}
    with patch(_PATCH_TARGET, AsyncMock()) as mock_esc:
        result = await _maybe_escalate(node_result, state)
    mock_esc.assert_not_called()
    assert "_escalation_performed" not in result


@pytest.mark.asyncio
async def test_maybe_escalate_error_count(mock_escalation_result):
    """Calls perform_escalation with is_technical_error=True when error_count >= 3."""
    state = {
        "conversation_id": "123",
        "customer_phone": "+5491100000000",
        "error_count": 3,
    }
    node_result = {}
    with patch(_PATCH_TARGET, AsyncMock(return_value=mock_escalation_result)) as mock_esc:
        await _maybe_escalate(node_result, state)
    mock_esc.assert_called_once()
    call_kwargs = mock_esc.call_args.kwargs if mock_esc.call_args.kwargs else {}
    call_args = mock_esc.call_args.args if mock_esc.call_args.args else ()
    # Build combined dict: positional args mapped to param names
    param_names = ["conversation_id", "customer_phone", "reason", "source", "is_technical_error"]
    combined = {param_names[i]: v for i, v in enumerate(call_args)}
    combined.update(call_kwargs)
    assert combined.get("is_technical_error") is True


@pytest.mark.asyncio
async def test_maybe_escalate_error_count_5_from_node_result(mock_escalation_result):
    """Triggers escalation when error_count >= 3 in node_result (not state)."""
    state = {
        "conversation_id": "456",
        "customer_phone": "+5491199999999",
        "error_count": 0,  # state has 0
    }
    node_result = {
        "error_count": 5,  # node_result has >= 3
    }
    with patch(_PATCH_TARGET, AsyncMock(return_value=mock_escalation_result)) as mock_esc:
        result = await _maybe_escalate(node_result, state)
    mock_esc.assert_called_once()
    assert result.get("_escalation_performed") is True


@pytest.mark.asyncio
async def test_maybe_escalate_skips_if_already_performed(mock_escalation_result):
    """Does NOT call perform_escalation again when _escalation_performed=True."""
    state = {
        "conversation_id": "123",
        "customer_phone": "+5491100000000",
        "escalation_triggered": True,
        "_escalation_performed": True,
        "error_count": 0,
    }
    node_result = {"escalation_triggered": True}
    with patch(_PATCH_TARGET, AsyncMock(return_value=mock_escalation_result)) as mock_esc:
        await _maybe_escalate(node_result, state)
    mock_esc.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_escalate_source_auto_error_when_technical(mock_escalation_result):
    """Uses source='auto_error' when is_technical (error_count >= 3)."""
    state = {
        "conversation_id": "789",
        "customer_phone": "+5491155555555",
        "error_count": 4,
    }
    node_result = {}
    with patch(_PATCH_TARGET, AsyncMock(return_value=mock_escalation_result)) as mock_esc:
        await _maybe_escalate(node_result, state)
    mock_esc.assert_called_once()
    call_kwargs = mock_esc.call_args.kwargs if mock_esc.call_args.kwargs else {}
    call_args = mock_esc.call_args.args if mock_esc.call_args.args else ()
    param_names = ["conversation_id", "customer_phone", "reason", "source", "is_technical_error"]
    combined = {param_names[i]: v for i, v in enumerate(call_args)}
    combined.update(call_kwargs)
    assert combined.get("source") == "auto_error"
