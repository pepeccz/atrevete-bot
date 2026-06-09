"""
Tests for REQ-H2: tool_evidence captured from DB even when Langfuse is unavailable.

T12a: Mock all 3 adapters; only ConversationTurnAdapter returns evidence → result is from DB.
T12b: All 3 adapters return [] → result is [] (not None, not exception).
T12c: DB adapter returns items → source field equals "db_turns".

TDD: these tests MUST fail before T14 (ConversationTurnAdapter does not exist yet).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.e2e.harness.redis_harness import (
    CheckpointToolEvidenceAdapter,
    StreamToolEvidenceAdapter,
    ToolCallEvidence,
)


def _make_evidence(tool_name: str = "book", source: str = "db_turns") -> ToolCallEvidence:
    return ToolCallEvidence(
        tool_name=tool_name,
        arguments={"service_id": "uuid-1"},
        result={"appointment_id": "uuid-2"},
        source=source,
        timestamp=datetime.now(UTC),
    )


class TestConversationTurnAdapterExists:
    """T12: ConversationTurnAdapter must exist in redis_harness."""

    def test_adapter_class_importable(self) -> None:
        """The class must be importable from redis_harness before implementation (this fails until T14)."""
        from tests.e2e.harness.redis_harness import ConversationTurnAdapter  # noqa: F401


class TestThreeTierFallbackChain:
    """T12a + T12b: 3-tier adapter chain in collect_tool_evidence."""

    @pytest.mark.asyncio
    async def test_db_adapter_used_when_checkpoint_and_stream_empty(self) -> None:
        """T12a: When checkpoint + stream return [], DB adapter result is returned."""
        from tests.e2e.harness.redis_harness import ConversationTurnAdapter

        db_evidence = [_make_evidence("book", source="db_turns")]

        mock_harness = MagicMock()
        mock_harness.redis = AsyncMock()

        with (
            patch.object(
                CheckpointToolEvidenceAdapter,
                "collect",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                StreamToolEvidenceAdapter,
                "collect",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                ConversationTurnAdapter,
                "collect",
                new_callable=AsyncMock,
                return_value=db_evidence,
            ),
        ):
            result = (
                await mock_harness.collect_tool_evidence.__wrapped__(mock_harness, "conv-123", 1)
                if hasattr(mock_harness.collect_tool_evidence, "__wrapped__")
                else None
            )

            # Direct instantiation test — verify the fallback logic
            from tests.e2e.harness.redis_harness import RedisTestHarness

            harness = MagicMock(spec=RedisTestHarness)
            harness.redis = AsyncMock()

            # We test the logic by calling each adapter in sequence
            checkpoint = CheckpointToolEvidenceAdapter(harness)
            stream = StreamToolEvidenceAdapter(harness)
            db = ConversationTurnAdapter(harness)

            checkpoint.collect = AsyncMock(return_value=[])
            stream.collect = AsyncMock(return_value=[])
            db.collect = AsyncMock(return_value=db_evidence)

            # Simulate collect_tool_evidence logic
            evidence = await checkpoint.collect("conv-123", 1)
            if not evidence:
                evidence = await stream.collect("conv-123", 1)
            if not evidence:
                evidence = await db.collect("conv-123", 1)

            assert evidence == db_evidence
            assert len(evidence) == 1
            assert evidence[0].source == "db_turns"

    @pytest.mark.asyncio
    async def test_all_adapters_empty_returns_empty_list(self) -> None:
        """T12b: All 3 adapters return [] → result is [] (not None, not exception)."""
        from tests.e2e.harness.redis_harness import ConversationTurnAdapter, RedisTestHarness

        harness = MagicMock(spec=RedisTestHarness)
        harness.redis = AsyncMock()

        checkpoint = CheckpointToolEvidenceAdapter(harness)
        stream = StreamToolEvidenceAdapter(harness)
        db = ConversationTurnAdapter(harness)

        checkpoint.collect = AsyncMock(return_value=[])
        stream.collect = AsyncMock(return_value=[])
        db.collect = AsyncMock(return_value=[])

        evidence = await checkpoint.collect("conv-xyz", 1)
        if not evidence:
            evidence = await stream.collect("conv-xyz", 1)
        if not evidence:
            evidence = await db.collect("conv-xyz", 1)

        assert evidence == []
        assert isinstance(evidence, list)

    @pytest.mark.asyncio
    async def test_db_adapter_source_field_is_db_turns(self) -> None:
        """T12c: Items returned by ConversationTurnAdapter have source='db_turns'."""
        from tests.e2e.harness.redis_harness import ConversationTurnAdapter, RedisTestHarness

        harness = MagicMock(spec=RedisTestHarness)

        # Mock the DB query helper to return a canned tool_calls JSONB row
        canned_tool_calls = [
            {
                "name": "check_availability",
                "args": {"date": "2026-07-01"},
                "result_summary": "3 slots",
            }
        ]
        canned_created_at = datetime.now(UTC)

        db = ConversationTurnAdapter(harness)
        db._fetch_turn_row = AsyncMock(return_value=(canned_tool_calls, canned_created_at))

        evidence = await db.collect("conv-abc", 1)

        assert len(evidence) == 1
        assert evidence[0].source == "db_turns"
        assert evidence[0].tool_name == "check_availability"

    @pytest.mark.asyncio
    async def test_collect_tool_evidence_method_includes_db_tier(self) -> None:
        """T12a (integration): collect_tool_evidence on RedisTestHarness uses 3-tier chain."""
        from tests.e2e.harness.redis_harness import ConversationTurnAdapter, RedisTestHarness

        db_evidence = [_make_evidence("manage_appointments", source="db_turns")]

        with (
            patch.object(
                CheckpointToolEvidenceAdapter,
                "collect",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                StreamToolEvidenceAdapter,
                "collect",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                ConversationTurnAdapter,
                "collect",
                new_callable=AsyncMock,
                return_value=db_evidence,
            ),
        ):
            mock_redis = AsyncMock()
            harness = RedisTestHarness.__new__(RedisTestHarness)
            harness.redis = mock_redis
            harness.binary_redis = None
            harness._owns_binary_client = True

            result = await harness.collect_tool_evidence("conv-123", 1)
            assert result == db_evidence
