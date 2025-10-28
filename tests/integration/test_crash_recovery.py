"""
Crash recovery tests for LangGraph checkpointing.

These tests verify that conversation state persists across agent restarts.
Most tests require Docker Compose to be running and are designed for manual validation.
"""

import pytest


@pytest.mark.skip(reason="Manual test - requires Docker Compose and agent restart")
def test_crash_recovery_manual():
    """
    Manual crash recovery test.

    This test validates that conversation state persists across agent restarts.
    It must be run manually with Docker Compose.

    Test Procedure:
    ===============

    1. Start all services:
       ```
       docker-compose up
       ```

    2. Send test message #1 via Redis CLI:
       ```
       docker-compose exec redis redis-cli
       PUBLISH incoming_messages '{"conversation_id":"crash-test-123","customer_phone":"+34612345678","message_text":"Test 1"}'
       ```

    3. Verify response in logs:
       ```
       docker-compose logs agent | grep "crash-test-123"
       ```
       Should see: "Graph completed for conversation_id=crash-test-123"

    4. Verify checkpoint exists in Redis:
       ```
       docker-compose exec redis redis-cli KEYS "checkpoint:crash-test-123:*"
       ```
       Should return checkpoint keys

    5. Stop agent container:
       ```
       docker-compose stop agent
       ```

    6. Restart agent container:
       ```
       docker-compose start agent
       ```

    7. Send test message #2 with same conversation_id:
       ```
       docker-compose exec redis redis-cli
       PUBLISH incoming_messages '{"conversation_id":"crash-test-123","customer_phone":"+34612345678","message_text":"Test 2"}'
       ```

    8. Verify agent responds (proves state recovered):
       ```
       docker-compose logs agent | grep "crash-test-123"
       ```
       Should see graph invocation and completion logs

    Expected Results:
    ================
    - Agent processes both messages successfully
    - Checkpoints persist in Redis across restart
    - No errors in agent logs during recovery

    Validation:
    ==========
    - Run `docker-compose logs agent` and verify no checkpoint-related errors
    - Verify both messages processed successfully
    - If integrated with Chatwoot, verify both WhatsApp messages received responses
    """
    pass


@pytest.mark.skip(reason="Requires Docker Compose environment")
@pytest.mark.asyncio
async def test_checkpoint_persistence():
    """
    Test that checkpoints persist in Redis.

    This test would verify checkpoint persistence but requires Docker Compose.
    For now, it's documented as a manual test.

    Automated Test Steps (when Docker is available):
    ================================================
    1. Create graph with Redis checkpointer
    2. Invoke graph with thread_id="test-persist-456"
    3. Verify checkpoint key exists in Redis
    4. Query checkpoint data from Redis
    5. Verify checkpoint contains state with messages
    """
    pass


def test_checkpointer_configuration():
    """Test that checkpointer can be created with correct configuration."""
    from agent.graphs.conversation_flow import create_conversation_graph
    from agent.state.checkpointer import get_redis_checkpointer

    # Verify checkpointer creation succeeds
    checkpointer = get_redis_checkpointer()
    assert checkpointer is not None

    # Verify graph can be created with checkpointer
    graph = create_conversation_graph(checkpointer=checkpointer)
    assert graph is not None

    # Note: Actual checkpoint operations require Redis to be running
    # Those are tested in Docker Compose environment
