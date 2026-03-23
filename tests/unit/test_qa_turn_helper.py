"""Unit tests for tests/e2e/harness/qa_turn_helper.py CLI wrapper.

Tests each subcommand by mocking Redis and harness dependencies,
verifying JSON output and exit codes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Patches target the *source* modules because qa_turn_helper uses local imports
# inside each async function (from shared.config import get_settings, etc.)
SETTINGS_PATCH = "shared.config.get_settings"
REDIS_FROM_URL_PATCH = "redis.asyncio.from_url"
REDIS_HARNESS_PATCH = "tests.e2e.harness.redis_harness.RedisTestHarness"
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
    """execute_turn returns valid dict -> stdout JSON with turn data."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    fake_result = {
        "turn_number": 1,
        "user_message": "Hola",
        "agent_response": "Bienvenida! En que puedo ayudarte?",
        "timestamp_sent": "2025-01-01T10:00:00+00:00",
        "timestamp_received": "2025-01-01T10:00:02+00:00",
        "response_latency_ms": 2000,
        "raw_response": {},
    }

    mock_harness = AsyncMock()
    mock_harness.execute_turn = AsyncMock(return_value=fake_result)
    mock_harness.close = AsyncMock()

    captured, mock_print = _capture_print()

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch(REDIS_HARNESS_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_turn

        await _cmd_turn(
            conversation_id="test-conv-123",
            message="Hola",
            phone="+34600000000",
            name="QA Test Client",
            timeout=30.0,
        )

    result = json.loads(captured[0])
    assert result["turn_number"] == 1
    assert result["agent_response"] == "Bienvenida! En que puedo ayudarte?"
    assert result["latency_ms"] == 2000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_timeout() -> None:
    """execute_turn raises TimeoutError -> stderr error JSON, exit 1."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    mock_harness = AsyncMock()
    mock_harness.execute_turn = AsyncMock(
        side_effect=TimeoutError("No response within 30.0s")
    )
    mock_harness.close = AsyncMock()

    captured, mock_print = _capture_print()

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch(REDIS_HARNESS_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
        pytest.raises(SystemExit) as exc_info,
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_turn

        await _cmd_turn(
            conversation_id="test-conv-123",
            message="Hola",
            phone="+34600000000",
            name="QA Test Client",
            timeout=30.0,
        )

    assert exc_info.value.code == 1
    result = json.loads(captured[0])
    assert result["ok"] is False
    assert result["error"] == "timeout"


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
    """capture_final_state returns checkpoint data -> stdout JSON with fields."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    fake_state = {
        "current_mode": "BOOKING",
        "mode_context": {"step": "slot_selection"},
        "customer_name": "Maria",
        "is_first_interaction": False,
        "error_count": 0,
        "mode_history": ["GREETING", "BOOKING"],
    }

    mock_harness = AsyncMock()
    mock_harness.capture_final_state = AsyncMock(return_value=fake_state)
    mock_harness.close = AsyncMock()

    captured, mock_print = _capture_print()

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch(REDIS_HARNESS_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_state

        await _cmd_state(conversation_id="test-conv-123")

    result = json.loads(captured[0])
    assert result["has_checkpoint"] is True
    assert result["current_mode"] == "BOOKING"
    assert result["customer_name"] == "Maria"
    assert result["mode_history"] == ["GREETING", "BOOKING"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_state_no_checkpoint() -> None:
    """capture_final_state returns None -> has_checkpoint=false."""
    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    mock_harness = AsyncMock()
    mock_harness.capture_final_state = AsyncMock(return_value=None)
    mock_harness.close = AsyncMock()

    captured, mock_print = _capture_print()

    with (
        patch(SETTINGS_PATCH, return_value=_fake_settings()),
        patch(REDIS_FROM_URL_PATCH, return_value=mock_client),
        patch(REDIS_HARNESS_PATCH, return_value=mock_harness),
        patch("builtins.print", mock_print),
    ):
        from tests.e2e.harness.qa_turn_helper import _cmd_state

        await _cmd_state(conversation_id="test-conv-123")

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
