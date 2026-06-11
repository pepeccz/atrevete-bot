"""Unit tests for tests/e2e/harness/qa_turn_helper.py CLI wrapper.

Tests each subcommand by mocking Redis and harness dependencies,
verifying JSON output and exit codes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch targets:
# - get_settings: imported locally inside each function → patch source module
# - redis.asyncio.from_url: imported locally inside each function → patch source module
# - RedisTestHarness: imported at TOP of qa_turn_helper (not locally) → patch usage site
# - StateResetHarness: imported locally inside _cmd_reset → patch source module
SETTINGS_PATCH = "shared.config.get_settings"
REDIS_FROM_URL_PATCH = "redis.asyncio.from_url"
REDIS_HARNESS_PATCH = "tests.e2e.harness.qa_turn_helper.RedisTestHarness"
STATE_RESET_PATCH = "tests.e2e.harness.state_reset.StateResetHarness"
HELPER_SCRIPT = "tests/e2e/harness/qa_turn_helper.py"


def _fake_settings() -> MagicMock:
    s = MagicMock()
    s.REDIS_URL = "redis://fake:6379"
    return s


def _capture_print() -> tuple[list[str], MagicMock]:
    """Return (captured_lines, mock_print) that records all positional print args."""
    captured: list[str] = []

    def _record(*args, **kwargs):
        if args:
            captured.append(str(args[0]))

    return captured, MagicMock(side_effect=_record)


# ---------------------------------------------------------------------------
# health subcommand
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_success() -> None:
    """Redis ping + exists succeed -> stdout JSON ok=true, stream=exists."""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.exists = AsyncMock(return_value=1)
    mock_client.aclose = AsyncMock()

    captured, mock_print = _capture_print()

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_health

        await _cmd_health()

    result = json.loads(captured[0])
    assert result == {"ok": True, "redis": "connected", "stream": "exists"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_redis_down() -> None:
    """Redis ping raises ConnectionError -> stderr JSON with error, exit 1."""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(side_effect=ConnectionError("Connection refused"))
    mock_client.aclose = AsyncMock()

    captured, mock_print = _capture_print()

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch("builtins.print", mock_print),
        pytest.raises(SystemExit) as exc_info,
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_health

        await _cmd_health()

    assert exc_info.value.code == 1
    result = json.loads(captured[0])
    assert result["ok"] is False
    assert result["error"] == "redis_connection_failed"
    assert "Connection refused" in result["details"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_stream_missing() -> None:
    """Redis ping OK but exists returns 0 -> stream=missing."""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.exists = AsyncMock(return_value=0)
    mock_client.aclose = AsyncMock()

    captured, mock_print = _capture_print()

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_health

        await _cmd_health()

    result = json.loads(captured[0])
    assert result == {"ok": True, "redis": "connected", "stream": "missing"}


# ---------------------------------------------------------------------------
# turn subcommand
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_success() -> None:
    """execute_turn returns valid dict -> stdout JSON with agent_response and timed_out."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    # Match the dict _cmd_turn actually reads from harness.execute_turn
    fake_result = {
        "agent_response": "Bienvenida! En que puedo ayudarte?",
        "timed_out": False,
        "response_latency_ms": 2000,
        "tool_evidence": [],
    }

    mock_harness = AsyncMock()
    mock_harness.execute_turn = AsyncMock(return_value=fake_result)
    mock_harness.close = AsyncMock()

    captured, mock_print = _capture_print()

    # _cmd_turn takes an argparse-style namespace object (args: Any)
    args = SimpleNamespace(
        conversation_id="test-conv-123",
        user_message="Hola",
        customer_phone="+34600000000",
        persona_name="QA Test Client",
        timeout=30.0,
    )

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch(REDIS_HARNESS_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_turn

        exit_code = await _cmd_turn(args)

    assert exit_code == 0
    result = json.loads(captured[0])
    assert result["agent_response"] == "Bienvenida! En que puedo ayudarte?"
    assert result["timed_out"] is False
    assert result["response_latency_ms"] == 2000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_timeout() -> None:
    """execute_turn returns timed_out=True -> stdout JSON with timed_out flag, exit 2."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    # _cmd_turn calls harness.execute_turn(raise_on_timeout=False) so timeout
    # is signaled via timed_out=True in the result dict, not by raising.
    timed_out_result = {
        "agent_response": None,
        "timed_out": True,
        "response_latency_ms": 0,
        "tool_evidence": [],
    }

    mock_harness = AsyncMock()
    mock_harness.execute_turn = AsyncMock(return_value=timed_out_result)
    mock_harness.close = AsyncMock()

    captured, mock_print = _capture_print()

    args = SimpleNamespace(
        conversation_id="test-conv-123",
        user_message="Hola",
        customer_phone="+34600000000",
        persona_name="QA Test Client",
        timeout=30.0,
    )

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch(REDIS_HARNESS_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_turn

        exit_code = await _cmd_turn(args)

    assert exit_code == 2
    result = json.loads(captured[0])
    assert result["timed_out"] is True
    assert result["agent_response"] is None


# ---------------------------------------------------------------------------
# reset subcommand
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_success() -> None:
    """reset_conversation_state returns cleanup counts -> stdout JSON."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    fake_result = {
        "checkpoints_deleted": 3,
        "customer_deleted": 1,
        "artifacts_deleted": 2,
        "clean": True,
    }

    mock_harness = AsyncMock()
    mock_harness.reset_conversation_state = AsyncMock(return_value=fake_result)

    captured, mock_print = _capture_print()

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch(STATE_RESET_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_reset

        await _cmd_reset(conversation_id="test-conv-123", phone="+34600000000")

    result = json.loads(captured[0])
    assert result["checkpoints_deleted"] == 3
    assert result["clean"] is True


# ---------------------------------------------------------------------------
# state subcommand
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_state_success() -> None:
    """capture_final_state returns checkpoint data -> stdout JSON with current AgentState fields."""
    # _cmd_state calls redis.from_url TWICE (text client + binary client).
    # Use side_effect to return a fresh AsyncMock for each call.
    mock_client_txt = AsyncMock()
    mock_client_txt.aclose = AsyncMock()
    mock_client_bin = AsyncMock()
    mock_client_bin.aclose = AsyncMock()

    # fake_state must use the post-create_agent AgentState field names.
    # current_mode / mode_history / is_first_interaction / error_count are gone.
    fake_state = {
        "conversation_id": "test-conv-123",
        "customer_phone": "+34999000001",
        "customer_id": "uuid-placeholder",
        "customer_name": "Maria",
        "messages": [],  # empty → messages_count=0, no ToolMessage scan needed
        "customer_consents": [],
        "conversation_summary": "Resumen de la conversacion.",
        "policy_accepted_at": None,
    }

    mock_harness = MagicMock()
    mock_harness.capture_final_state = AsyncMock(return_value=fake_state)
    mock_harness.close = AsyncMock()

    captured, mock_print = _capture_print()

    # _cmd_state takes an argparse-style namespace: args.conversation_id
    args = SimpleNamespace(conversation_id="test-conv-123")

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, side_effect=[mock_client_txt, mock_client_bin]),
        patch(REDIS_HARNESS_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_state

        await _cmd_state(args)

    result = json.loads(captured[0])
    assert result["has_checkpoint"] is True
    assert result["customer_name"] == "Maria"
    assert result["messages_count"] == 0
    assert result["summary_present"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_state_no_checkpoint() -> None:
    """capture_final_state returns None -> has_checkpoint=false."""
    mock_client_txt = AsyncMock()
    mock_client_txt.aclose = AsyncMock()
    mock_client_bin = AsyncMock()
    mock_client_bin.aclose = AsyncMock()

    mock_harness = MagicMock()
    mock_harness.capture_final_state = AsyncMock(return_value=None)
    mock_harness.close = AsyncMock()

    captured, mock_print = _capture_print()

    args = SimpleNamespace(conversation_id="test-conv-123")

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, side_effect=[mock_client_txt, mock_client_bin]),
        patch(REDIS_HARNESS_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_state

        await _cmd_state(args)

    result = json.loads(captured[0])
    assert result == {"has_checkpoint": False}


# ---------------------------------------------------------------------------
# CLI argument parsing (invalid subcommand)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_invalid_subcommand() -> None:
    """Run with invalid args -> non-zero exit code."""
    result = subprocess.run(
        [sys.executable, HELPER_SCRIPT, "invalid_command"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
