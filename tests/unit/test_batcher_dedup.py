"""Unit tests for MessageBatcher intra-batch content deduplication.

Tests scenarios S1–S3 from spec: fix-booking-duplicate-response.
"""

from unittest.mock import AsyncMock, patch

import pytest

from agent.batching.message_batcher import MessageBatcher


@pytest.mark.asyncio
async def test_s1_duplicate_message_in_same_batch_skipped():
    """S1: Two identical messages in the same batch → callback receives only one."""
    received: list[dict] = []

    async def callback(conversation_id: str, messages: list[dict]) -> None:
        received.extend(messages)

    batcher = MessageBatcher(window_seconds=30)
    batcher.set_callback(callback)

    with patch.object(batcher, "_persist_batch", new=AsyncMock()):
        # Add same message twice
        await batcher.add_message("conv-001", {"message_text": "Hola"})
        await batcher.add_message("conv-001", {"message_text": "Hola"})

    # Flush manually to trigger callback
    with patch.object(batcher, "_persist_batch", new=AsyncMock()):
        with patch.object(batcher, "_clear_persisted_batch", new=AsyncMock()):
            await batcher.flush_all()

    assert len(received) == 1
    assert received[0]["message_text"] == "Hola"


@pytest.mark.asyncio
async def test_s1_duplicate_emits_warning_log():
    """S1: Duplicate message must emit a WARNING log with conversation_id."""
    batcher = MessageBatcher(window_seconds=30)
    batcher.set_callback(AsyncMock())

    with patch.object(batcher, "_persist_batch", new=AsyncMock()):
        await batcher.add_message("conv-001", {"message_text": "Hola"})

        import logging

        with patch.object(
            logging.getLogger("agent.batching.message_batcher"),
            "warning",
        ) as mock_warn:
            # Re-patch batcher's persist for the second call
            with patch.object(batcher, "_persist_batch", new=AsyncMock()):
                await batcher.add_message("conv-001", {"message_text": "Hola"})

            # Warning must have been emitted
            assert mock_warn.called
            # The warning args should include conversation_id
            call_args = str(mock_warn.call_args_list)
            assert "conv-001" in call_args


@pytest.mark.asyncio
async def test_s2_different_messages_in_same_batch_both_processed():
    """S2: Two different messages → callback receives both."""
    received: list[dict] = []

    async def callback(conversation_id: str, messages: list[dict]) -> None:
        received.extend(messages)

    batcher = MessageBatcher(window_seconds=30)
    batcher.set_callback(callback)

    with patch.object(batcher, "_persist_batch", new=AsyncMock()):
        await batcher.add_message("conv-002", {"message_text": "Hola"})
        await batcher.add_message("conv-002", {"message_text": "¿Qué servicios tienen?"})

    with patch.object(batcher, "_persist_batch", new=AsyncMock()):
        with patch.object(batcher, "_clear_persisted_batch", new=AsyncMock()):
            await batcher.flush_all()

    assert len(received) == 2
    assert received[0]["message_text"] == "Hola"
    assert received[1]["message_text"] == "¿Qué servicios tienen?"


@pytest.mark.asyncio
async def test_s2_no_warning_for_different_messages():
    """S2: No WARNING is emitted when messages differ."""
    batcher = MessageBatcher(window_seconds=30)
    batcher.set_callback(AsyncMock())

    with patch.object(batcher, "_persist_batch", new=AsyncMock()):
        await batcher.add_message("conv-002", {"message_text": "Hola"})

        import logging

        with patch.object(
            logging.getLogger("agent.batching.message_batcher"),
            "warning",
        ) as mock_warn:
            with patch.object(batcher, "_persist_batch", new=AsyncMock()):
                await batcher.add_message("conv-002", {"message_text": "¿Qué servicios tienen?"})

            assert not mock_warn.called


@pytest.mark.asyncio
async def test_s3_same_text_in_consecutive_batches_both_processed():
    """S3: Same message text in separate batches → both are processed (no cross-batch dedup)."""
    received_batches: list[list[dict]] = []

    async def callback(conversation_id: str, messages: list[dict]) -> None:
        received_batches.append(list(messages))

    # Use window=0 so each message is processed immediately as its own batch
    batcher = MessageBatcher(window_seconds=0)
    batcher.set_callback(callback)

    await batcher.add_message("conv-003", {"message_text": "Hola"})
    await batcher.add_message("conv-003", {"message_text": "Hola"})

    # Both immediate batches (window=0) should have been sent
    assert len(received_batches) == 2
    assert received_batches[0][0]["message_text"] == "Hola"
    assert received_batches[1][0]["message_text"] == "Hola"


@pytest.mark.asyncio
async def test_non_duplicate_after_different_message_is_accepted():
    """Edge case: A B A pattern — second A is not consecutive with first A, so it's allowed."""
    received: list[dict] = []

    async def callback(conversation_id: str, messages: list[dict]) -> None:
        received.extend(messages)

    batcher = MessageBatcher(window_seconds=30)
    batcher.set_callback(callback)

    with patch.object(batcher, "_persist_batch", new=AsyncMock()):
        await batcher.add_message("conv-004", {"message_text": "Hola"})
        await batcher.add_message("conv-004", {"message_text": "¿Horarios?"})
        await batcher.add_message("conv-004", {"message_text": "Hola"})

    with patch.object(batcher, "_persist_batch", new=AsyncMock()):
        with patch.object(batcher, "_clear_persisted_batch", new=AsyncMock()):
            await batcher.flush_all()

    assert len(received) == 3
    texts = [m["message_text"] for m in received]
    assert texts == ["Hola", "¿Horarios?", "Hola"]
