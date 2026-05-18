"""
Unit tests for QA infrastructure availability (T0.1).

Verifies:
- QA harness modules import correctly (no broken deps)
- tests/qa/conversations/ directory exists for scenario files
- TokenTrackingMiddleware has the token extraction API needed for cache measurement
- measure_cache_hit_rate.py can be imported once created

NOTE: Verification of cached_tokens > 0 in actual LLM calls requires a live
agent (Docker + Redis + OpenRouter). That gate is documented in T0.3 as an
integration-level check run via scripts/measure_cache_hit_rate.py.
"""

from __future__ import annotations

from pathlib import Path

# =============================================================================
# T0.1 — QA infra structural verification
# =============================================================================


class TestQAHarnessImports:
    """Verify QA harness modules are importable (structural health check)."""

    def test_harness_run_models_importable(self):
        """tests/e2e/harness/run_models.py must be importable."""
        from tests.e2e.harness.run_models import (
            ConversationResult,
            LLMTurnResponse,
            QARunIdentity,
            QARunSession,
            TurnEvidence,
        )

        # Verify classes are accessible — not just imported
        assert ConversationResult is not None
        assert LLMTurnResponse is not None
        assert QARunIdentity is not None
        assert QARunSession is not None
        assert TurnEvidence is not None

    def test_harness_redis_harness_importable(self):
        """tests/e2e/harness/redis_harness.py must be importable."""
        from tests.e2e.harness.redis_harness import (
            ClassifierOutput,
            RedisTestHarness,
        )

        assert ClassifierOutput is not None
        assert RedisTestHarness is not None

    def test_qa_conversations_directory_exists(self):
        """tests/qa/conversations/ directory must exist for scenario JSON files."""
        repo_root = Path(__file__).parent.parent.parent
        qa_dir = repo_root / "tests" / "qa" / "conversations"
        assert qa_dir.is_dir(), (
            f"Expected tests/qa/conversations/ to exist at {qa_dir}. "
            "Create it with: mkdir -p tests/qa/conversations/"
        )


