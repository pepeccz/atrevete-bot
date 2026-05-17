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


class TestTokenTrackingAPIForMeasurement:
    """Verify TokenTrackingMiddleware exposes the API needed by measure_cache_hit_rate.py."""

    def test_extract_token_counts_function_importable(self):
        """_extract_token_counts helper must be importable for use in measure script."""
        from agent.middleware.token_tracking import _extract_token_counts

        assert callable(_extract_token_counts)

    def test_extract_token_counts_from_usage_metadata(self):
        """_extract_token_counts must read input/output tokens from usage_metadata."""
        from unittest.mock import MagicMock

        from agent.middleware.token_tracking import _extract_token_counts

        msg = MagicMock()
        msg.usage_metadata = {"input_tokens": 500, "output_tokens": 50}
        msg.response_metadata = {}

        input_t, output_t = _extract_token_counts(msg)
        assert input_t == 500
        assert output_t == 50

    def test_extract_token_counts_from_response_metadata(self):
        """_extract_token_counts must fall back to response_metadata.token_usage."""
        from unittest.mock import MagicMock

        from agent.middleware.token_tracking import _extract_token_counts

        msg = MagicMock()
        msg.usage_metadata = None  # Not populated by this provider
        msg.response_metadata = {
            "token_usage": {"prompt_tokens": 800, "completion_tokens": 120}
        }

        input_t, output_t = _extract_token_counts(msg)
        assert input_t == 800
        assert output_t == 120

    def test_extract_token_counts_returns_zeros_when_empty(self):
        """_extract_token_counts must return (0, 0) when no usage data available."""
        from unittest.mock import MagicMock

        from agent.middleware.token_tracking import _extract_token_counts

        msg = MagicMock()
        msg.usage_metadata = None
        msg.response_metadata = {}

        input_t, output_t = _extract_token_counts(msg)
        assert input_t == 0
        assert output_t == 0
