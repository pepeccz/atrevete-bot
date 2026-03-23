"""Integration test for qa_turn_helper CLI against live Docker stack.

Requires Redis (and the full agent stack) running via docker-compose.
Marked with @pytest.mark.e2e — skipped automatically if Redis is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from uuid import uuid4

import pytest

HELPER_SCRIPT = "tests/e2e/harness/qa_turn_helper.py"
TEST_PHONE = "+34999999999"


def _redis_available() -> bool:
    """Check if Redis is reachable by running the health subcommand."""
    try:
        result = subprocess.run(
            [sys.executable, HELPER_SCRIPT, "health"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout.strip())
        return data.get("ok") is True and data.get("redis") == "connected"
    except Exception:
        return False


@pytest.mark.e2e
@pytest.mark.skipif(not _redis_available(), reason="Redis not available (Docker stack not running)")
class TestQATurnHelperLive:
    """Full turn cycle against the live Docker stack."""

    def test_full_turn_cycle(self) -> None:
        """health → reset → turn → reset cleanup."""
        conversation_id = str(uuid4())

        # 1. Health check
        health_result = subprocess.run(
            [sys.executable, HELPER_SCRIPT, "health"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert health_result.returncode == 0, f"health failed: {health_result.stderr}"
        health_data = json.loads(health_result.stdout.strip())
        assert health_data["ok"] is True
        assert health_data["redis"] == "connected"

        # 2. Reset (pre-clean to ensure no stale state)
        reset_result = subprocess.run(
            [
                sys.executable,
                HELPER_SCRIPT,
                "reset",
                "--conversation-id",
                conversation_id,
                "--phone",
                TEST_PHONE,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert reset_result.returncode == 0, f"reset failed: {reset_result.stderr}"

        # 3. Turn — send "Hola" and expect a response
        turn_result = subprocess.run(
            [
                sys.executable,
                HELPER_SCRIPT,
                "turn",
                "--conversation-id",
                conversation_id,
                "--message",
                "Hola",
                "--phone",
                TEST_PHONE,
                "--timeout",
                "60",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert turn_result.returncode == 0, f"turn failed: {turn_result.stderr}"
        turn_data = json.loads(turn_result.stdout.strip())
        assert "turn_number" in turn_data
        assert "agent_response" in turn_data
        assert "latency_ms" in turn_data
        assert turn_data["turn_number"] == 1
        assert isinstance(turn_data["agent_response"], str)
        assert len(turn_data["agent_response"]) > 0

        # 4. Reset cleanup
        cleanup_result = subprocess.run(
            [
                sys.executable,
                HELPER_SCRIPT,
                "reset",
                "--conversation-id",
                conversation_id,
                "--phone",
                TEST_PHONE,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert cleanup_result.returncode == 0, f"cleanup reset failed: {cleanup_result.stderr}"
        cleanup_data = json.loads(cleanup_result.stdout.strip())
        assert "checkpoints_deleted" in cleanup_data
        assert "clean" in cleanup_data
