"""T20 — I4: Integration test for turn-2 context-loss regression.

Spec: REQ-I4 / SC-I4-A, SC-I4-B, SC-I4-C, SC-I4-D

This test drives a 2-turn conversation programmatically through the agent and
asserts that the turn-2 response is NOT a verbatim copy of the turn-1 response.

The test uses a sentinel string ("XYZZY_TURN2_SENTINEL") in the turn-2 message.
If context-loss is present, the bot will repeat its turn-1 response verbatim
regardless of the turn-2 content.

Hypothesis being tested (per design doc):
- H1: LLM doesn't see user input (raw token loss before LLM)
- H2: SummarizeMiddleware swallows turn-2 user message
- H3: Redis Stream dedup drops turn 2

This is an integration test that requires the live agent pipeline (Redis + agent
container running). It skips gracefully when the agent is unreachable.

If the test fails, it proves the context-loss bug is present and the fix must
address the root cause. If the agent is unreachable, the test skips — this is
acceptable per SC-I4-D which allows a documented-follow-up outcome for I4.
"""

from __future__ import annotations

import socket
from datetime import UTC
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _redis_usable() -> bool:
    """Return True if Redis is reachable AND accepts connections without auth errors.

    A local Redis that is running but requires a password is NOT usable for the
    QA harness test (which needs to publish to INCOMING_STREAM without auth).
    The production Redis on the server has credentials configured via .env;
    local Redis may not.
    """
    try:
        s = socket.create_connection(("localhost", 6379), timeout=1)
        s.close()
    except OSError:
        return False

    # Quick auth check: send PING, check for AUTH error in response
    import socket as _socket

    try:
        s = _socket.create_connection(("localhost", 6379), timeout=2)
        s.sendall(b"*1\r\n$4\r\nPING\r\n")
        response = s.recv(64)
        s.close()
        # If response starts with '-ERR' or '-NOAUTH', Redis requires auth
        if response.startswith(b"-") and (b"AUTH" in response or b"NOAUTH" in response):
            return False
        return True
    except OSError:
        return False


def _normalized_overlap(s1: str, s2: str) -> float:
    """Return approximate character overlap ratio between two strings.

    Uses the longer string as the denominator to detect when one is a
    near-copy of the other.
    """
    if not s1 or not s2:
        return 0.0

    # Simple character overlap: count chars in common
    shorter, longer = (s1, s2) if len(s1) <= len(s2) else (s2, s1)
    common = sum(1 for c in shorter if c in longer)
    return common / max(len(longer), 1)


@pytest.mark.skipif(
    not _redis_usable(),
    reason=(
        "Redis not reachable on localhost:6379 — skipping live turn-2 context-loss test. "
        "Per SC-I4-D this is acceptable: I4 is documented as a follow-up (Change K) if "
        "the agent pipeline is not available locally."
    ),
)
@pytest.mark.asyncio
async def test_turn2_response_differs_from_turn1() -> None:
    """SC-I4-A/B: Turn-2 response must NOT be a verbatim copy of turn-1 response.

    Drives a 2-turn conversation:
    - Turn 1: "Hola, quiero reservar una cita"
    - Turn 2: "XYZZY_TURN2_SENTINEL quiero un corte de pelo"

    The turn-2 response must differ substantially from turn-1 (overlap < 90%).
    If the bot repeats turn-1 verbatim on turn 2, this test fails proving context loss.
    """
    import time
    import uuid
    from datetime import datetime

    from tests.e2e.harness.redis_harness import RedisTestHarness
    from tests.e2e.harness.run_models import QARunIdentity, QARunSession

    SENTINEL = "XYZZY_TURN2_SENTINEL"
    conv_id = str(uuid.uuid4())
    phone = "+34999099901"  # Out of normal range, clearly test-only

    import redis.asyncio as aioredis

    from shared.config import get_settings

    settings = get_settings()
    redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    client = aioredis.from_url(redis_url)

    harness = RedisTestHarness(redis_client=client)

    try:
        identity = QARunIdentity(
            conversation_id=conv_id,
            customer_phone=phone,
            sender_name="Test User",
            run_started_at=datetime.now(UTC),
        )

        # Turn 1
        session1 = QARunSession(identity=identity, started_monotonic=time.monotonic())
        result1 = await harness.execute_turn(
            user_message="Hola, quiero reservar una cita",
            session=session1,
            timeout=60.0,
            raise_on_timeout=False,
        )

        if result1.get("timed_out"):
            pytest.skip("Agent did not respond to turn 1 — likely agent container not running")

        turn1_response = result1.get("agent_response", "")
        assert turn1_response, "Turn-1 response is empty"

        # Turn 2 — with sentinel to confirm user input is not lost
        session2 = QARunSession(identity=identity, started_monotonic=time.monotonic())
        result2 = await harness.execute_turn(
            user_message=f"{SENTINEL} quiero un corte de pelo",
            session=session2,
            timeout=60.0,
            raise_on_timeout=False,
        )

        if result2.get("timed_out"):
            pytest.skip("Agent did not respond to turn 2 — likely agent container not running")

        turn2_response = result2.get("agent_response", "")
        assert turn2_response, "Turn-2 response is empty"

        # SC-I4-A: Responses must be substantially different
        overlap = _normalized_overlap(turn1_response, turn2_response)
        assert overlap < 0.90, (
            f"Turn-2 response has {overlap:.1%} character overlap with turn-1 response, "
            f"which indicates context-loss (verbatim repetition). "
            f"Turn 1: {turn1_response[:200]!r}\n"
            f"Turn 2: {turn2_response[:200]!r}\n"
            "Root cause hypotheses: H1 (prompt assembly), H2 (SummarizeMiddleware), "
            "or H3 (Redis Stream dedup). See design doc for investigation plan."
        )

        # Additional: if the sentinel is echoed in turn-2 response, that suggests
        # the bot IS processing the turn-2 message (rules out H1/H3)
        # We don't assert this positively — it would only be relevant if the test fails.

    finally:
        await client.aclose()
