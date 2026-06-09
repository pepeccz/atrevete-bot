"""
Integration test for REQ-H2: ConversationTurnAdapter reads from conversation_turns.

T13: Insert a conversation_history + conversation_turns row with tool_calls JSONB,
     drain Redis qa_tool_trace, assert collect_tool_evidence returns DB evidence
     with source="db_turns".

This test requires a live PostgreSQL + Redis connection.
It is skipped automatically when either is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

# Skip entire module if async DB is unavailable
pytest_asyncio_mode = "auto"


def _is_pg_available() -> bool:
    """Quick check: can we import and connect to Postgres synchronously."""
    try:
        import os

        import psycopg2  # noqa: F401

        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db",
        )
        # Extract sync URL from async URL
        sync_url = db_url.replace("+asyncpg", "").replace("+psycopg", "")

        conn = psycopg2.connect(sync_url, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


def _is_redis_available() -> bool:
    try:
        import redis as sync_redis

        r = sync_redis.from_url("redis://localhost:6379/0", socket_connect_timeout=1)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


PG_AVAILABLE = _is_pg_available()
REDIS_AVAILABLE = _is_redis_available()

pytestmark = pytest.mark.skipif(
    not (PG_AVAILABLE and REDIS_AVAILABLE),
    reason="Requires live PostgreSQL + Redis (docker compose services must be running)",
)


@pytest.mark.asyncio
async def test_conversation_turn_adapter_reads_tool_calls() -> None:
    """
    T13: Insert a ConversationHistory + ConversationTurn row with tool_calls JSONB,
    assert ConversationTurnAdapter.collect() returns ToolCallEvidence with source='db_turns'.
    """
    import redis.asyncio as aioredis
    import sqlalchemy.ext.asyncio as sqla_async
    from sqlalchemy import text

    from tests.e2e.harness.redis_harness import (
        ConversationTurnAdapter,
        RedisTestHarness,
    )

    # Unique IDs for this test run
    test_conv_id = f"qa-test-{uuid.uuid4()}"
    test_phone = "+34999000099"  # Safe sandbox phone, not in scenarios

    # Build async engine
    import os

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db",
    )

    engine = sqla_async.create_async_engine(db_url, echo=False)

    history_id = uuid.uuid4()
    turn_tool_calls = [
        {"name": "book", "args": {"service_id": str(uuid.uuid4())}, "result_summary": "booked ok"}
    ]

    try:
        async with engine.begin() as conn:
            # Insert a minimal ConversationHistory row
            await conn.execute(
                text("""
                    INSERT INTO conversation_history
                        (id, conversation_id, chatwoot_conversation_id, atencion_automatica,
                         started_at, last_activity_at)
                    VALUES
                        (:id, :conv_id, :cw_id, true, now(), now())
                    """),
                {
                    "id": history_id,
                    "conv_id": test_conv_id,
                    "cw_id": 999999,
                },
            )

            # Insert a ConversationTurn row with tool_calls JSONB
            import json

            await conn.execute(
                text("""
                    INSERT INTO conversation_turns
                        (id, conversation_history_id, turn_number, latency_ms, tool_calls, created_at)
                    VALUES
                        (:id, :hist_id, 1, 500, CAST(:tool_calls AS jsonb), now())
                    """),
                {
                    "id": uuid.uuid4(),
                    "hist_id": history_id,
                    "tool_calls": json.dumps(turn_tool_calls),
                },
            )

        # Drain Redis qa_tool_trace stream (simulate Langfuse unavailable path)
        redis_client = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
        stream_key = f"qa_tool_trace:{test_conv_id}"
        # Delete the stream so CheckpointToolEvidenceAdapter + StreamToolEvidenceAdapter return []
        await redis_client.delete(stream_key)

        # Build harness with a mock-ish redis
        harness = RedisTestHarness.__new__(RedisTestHarness)
        harness.redis = redis_client
        harness.binary_redis = None
        harness._owns_binary_client = False

        # Patch capture_final_state to return None (no checkpoint)
        from unittest.mock import AsyncMock

        harness.capture_final_state = AsyncMock(return_value=None)

        # Inject the DB engine into the adapter (we need to pass a way for adapter to reach DB)
        adapter = ConversationTurnAdapter(harness)
        adapter._engine = engine

        evidence = await adapter.collect(test_conv_id, 1)

        assert len(evidence) >= 1, f"Expected at least 1 evidence item, got: {evidence}"
        assert evidence[0].source == "db_turns"
        assert evidence[0].tool_name == "book"

        await redis_client.aclose()

    finally:
        # Cleanup: delete the test rows
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM conversation_history WHERE id = :id"),
                {"id": history_id},
            )
        await engine.dispose()
