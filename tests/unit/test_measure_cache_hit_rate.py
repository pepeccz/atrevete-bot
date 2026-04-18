"""
Unit tests for scripts/measure_cache_hit_rate.py (T0.2).

Tests cover:
- extract_turn_token_usage: reading from multiple token data locations
- compute_turn_ratio: ratio calculation and edge cases
- compute_cache_hit_rate: full trace processing and aggregation
- CLI (main) smoke test with temp file

All tests are synchronous — no LLM, no Docker, no Redis needed.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from scripts.measure_cache_hit_rate import (
    compute_cache_hit_rate,
    compute_turn_ratio,
    extract_turn_token_usage,
    load_trace,
    save_result,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_turn_with_openai_usage(
    turn_number: int = 1,
    cached_tokens: int = 400,
    prompt_tokens: int = 800,
    completion_tokens: int = 100,
) -> dict:
    """Build a turn dict with OpenAI-style token_usage in raw_response."""
    return {
        "turn_number": turn_number,
        "user_message": "Hola",
        "agent_response": "¡Hola!",
        "response_latency_ms": 500,
        "timed_out": False,
        "raw_response": {
            "token_usage": {
                "cached_tokens": cached_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        },
    }


def _make_turn_with_langchain_usage(
    turn_number: int = 1,
    input_tokens: int = 600,
    output_tokens: int = 80,
    cache_read: int = 300,
) -> dict:
    """Build a turn dict with LangChain usage_metadata in raw_response."""
    return {
        "turn_number": turn_number,
        "user_message": "Quiero corte",
        "agent_response": "¿Para señora?",
        "response_latency_ms": 600,
        "timed_out": False,
        "raw_response": {
            "usage_metadata": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "input_token_details": {"cache_read": cache_read},
            }
        },
    }


def _make_turn_no_usage(turn_number: int = 1) -> dict:
    """Build a turn dict with no token data."""
    return {
        "turn_number": turn_number,
        "user_message": "Hola",
        "agent_response": "¡Hola!",
        "response_latency_ms": 400,
        "timed_out": False,
        "raw_response": {},
    }


def _make_trace(*turns, scenario_id: str = "test_scenario") -> dict:
    """Build a full trace dict."""
    return {
        "scenario_id": scenario_id,
        "conversation_id": "test-conv-id",
        "turns": list(turns),
    }


# =============================================================================
# extract_turn_token_usage
# =============================================================================


class TestExtractTurnTokenUsage:
    """Tests for extract_turn_token_usage() pure function."""

    def test_reads_openai_style_token_usage(self):
        """Must extract cached, prompt, completion from token_usage dict."""
        turn = _make_turn_with_openai_usage(
            cached_tokens=400, prompt_tokens=800, completion_tokens=100
        )
        usage = extract_turn_token_usage(turn)
        assert usage["cached_tokens"] == 400
        assert usage["prompt_tokens"] == 800
        assert usage["completion_tokens"] == 100

    def test_reads_langchain_usage_metadata(self):
        """Must extract tokens from usage_metadata (LangChain format) when token_usage absent."""
        turn = _make_turn_with_langchain_usage(
            input_tokens=600, output_tokens=80, cache_read=300
        )
        usage = extract_turn_token_usage(turn)
        assert usage["cached_tokens"] == 300
        assert usage["prompt_tokens"] == 600
        assert usage["completion_tokens"] == 80

    def test_returns_none_values_when_no_token_data(self):
        """Must return all-None dict when raw_response has no token info."""
        turn = _make_turn_no_usage()
        usage = extract_turn_token_usage(turn)
        assert usage["cached_tokens"] is None
        assert usage["prompt_tokens"] is None
        assert usage["completion_tokens"] is None

    def test_returns_none_for_missing_raw_response(self):
        """Must handle turns without raw_response key gracefully."""
        turn = {"turn_number": 1, "user_message": "Hola", "agent_response": "¡Hola!"}
        usage = extract_turn_token_usage(turn)
        assert usage["cached_tokens"] is None
        assert usage["prompt_tokens"] is None


# =============================================================================
# compute_turn_ratio
# =============================================================================


class TestComputeTurnRatio:
    """Tests for compute_turn_ratio() pure function."""

    def test_computes_ratio_correctly(self):
        """Ratio must be cached_tokens / prompt_tokens."""
        usage = {"cached_tokens": 400, "prompt_tokens": 800, "completion_tokens": 100}
        ratio = compute_turn_ratio(usage)
        assert ratio == pytest.approx(0.5, rel=1e-4)

    def test_returns_none_when_prompt_tokens_zero(self):
        """Must return None when prompt_tokens == 0 (avoid division by zero)."""
        usage = {"cached_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}
        ratio = compute_turn_ratio(usage)
        assert ratio is None

    def test_returns_none_when_prompt_tokens_none(self):
        """Must return None when prompt_tokens is None (unavailable data)."""
        usage = {"cached_tokens": None, "prompt_tokens": None, "completion_tokens": None}
        ratio = compute_turn_ratio(usage)
        assert ratio is None

    def test_zero_cached_tokens_gives_zero_ratio(self):
        """cached_tokens == 0 with valid prompt_tokens must yield ratio == 0.0."""
        usage = {"cached_tokens": 0, "prompt_tokens": 500, "completion_tokens": 60}
        ratio = compute_turn_ratio(usage)
        assert ratio == pytest.approx(0.0, abs=1e-6)

    def test_full_cache_hit_ratio_is_one(self):
        """When cached_tokens == prompt_tokens, ratio == 1.0."""
        usage = {"cached_tokens": 500, "prompt_tokens": 500, "completion_tokens": 60}
        ratio = compute_turn_ratio(usage)
        assert ratio == pytest.approx(1.0, rel=1e-4)


# =============================================================================
# compute_cache_hit_rate
# =============================================================================


class TestComputeCacheHitRate:
    """Tests for compute_cache_hit_rate() — full trace aggregation."""

    def test_single_turn_with_data(self):
        """Single-turn trace with token data must compute avg_ratio correctly."""
        turn = _make_turn_with_openai_usage(cached_tokens=400, prompt_tokens=800)
        trace = _make_trace(turn)
        result = compute_cache_hit_rate(trace)

        assert result["turns_total"] == 1
        assert result["turns_with_data"] == 1
        assert result["avg_ratio"] == pytest.approx(0.5, rel=1e-4)

    def test_multiple_turns_averages_correctly(self):
        """Multi-turn trace must compute the arithmetic mean of valid ratios."""
        turn1 = _make_turn_with_openai_usage(
            turn_number=1, cached_tokens=400, prompt_tokens=800
        )  # ratio = 0.5
        turn2 = _make_turn_with_openai_usage(
            turn_number=2, cached_tokens=600, prompt_tokens=1000
        )  # ratio = 0.6
        trace = _make_trace(turn1, turn2)
        result = compute_cache_hit_rate(trace)

        assert result["turns_total"] == 2
        assert result["turns_with_data"] == 2
        assert result["avg_ratio"] == pytest.approx(0.55, rel=1e-4)

    def test_turns_without_data_excluded_from_average(self):
        """Turns without token data must NOT affect avg_ratio."""
        turn_with_data = _make_turn_with_openai_usage(
            turn_number=1, cached_tokens=400, prompt_tokens=800
        )  # ratio = 0.5
        turn_no_data = _make_turn_no_usage(turn_number=2)
        trace = _make_trace(turn_with_data, turn_no_data)
        result = compute_cache_hit_rate(trace)

        assert result["turns_total"] == 2
        assert result["turns_with_data"] == 1
        assert result["avg_ratio"] == pytest.approx(0.5, rel=1e-4)

    def test_all_turns_without_data_gives_null_ratio(self):
        """When no turns have token data, avg_ratio must be None."""
        trace = _make_trace(_make_turn_no_usage(1), _make_turn_no_usage(2))
        result = compute_cache_hit_rate(trace)

        assert result["turns_total"] == 2
        assert result["turns_with_data"] == 0
        assert result["avg_ratio"] is None
        assert "No token_usage data" in result["note"]

    def test_empty_trace_gives_zero_turns(self):
        """Empty turns list must be handled gracefully."""
        trace = _make_trace()
        result = compute_cache_hit_rate(trace)

        assert result["turns_total"] == 0
        assert result["turns_with_data"] == 0
        assert result["avg_ratio"] is None

    def test_result_includes_scenario_and_conversation_id(self):
        """Result dict must include scenario and conversation_id from trace."""
        turn = _make_turn_with_openai_usage()
        trace = _make_trace(turn, scenario_id="baseline_booking")
        trace["conversation_id"] = "conv-abc-123"
        result = compute_cache_hit_rate(trace)

        assert result["scenario"] == "baseline_booking"
        assert result["conversation_id"] == "conv-abc-123"

    def test_per_turn_breakdown_has_correct_keys(self):
        """Each entry in result['turns'] must have the expected keys."""
        turn = _make_turn_with_openai_usage(turn_number=1, cached_tokens=300, prompt_tokens=900)
        trace = _make_trace(turn)
        result = compute_cache_hit_rate(trace)

        assert "0" in result["turns"]
        t = result["turns"]["0"]
        assert "turn_number" in t
        assert "cached_tokens" in t
        assert "prompt_tokens" in t
        assert "completion_tokens" in t
        assert "ratio" in t
        assert t["turn_number"] == 1
        assert t["cached_tokens"] == 300
        assert t["prompt_tokens"] == 900
        assert t["ratio"] == pytest.approx(300 / 900, rel=1e-4)


# =============================================================================
# I/O: load_trace, save_result
# =============================================================================


class TestIOFunctions:
    """Tests for load_trace() and save_result()."""

    def test_load_trace_reads_json(self):
        """load_trace must parse a valid JSON file."""
        trace = {"scenario_id": "test", "turns": []}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(trace, f)
            tmp_path = f.name
        try:
            loaded = load_trace(tmp_path)
            assert loaded["scenario_id"] == "test"
        finally:
            os.unlink(tmp_path)

    def test_load_trace_raises_on_missing_file(self):
        """load_trace must raise FileNotFoundError for non-existent paths."""
        with pytest.raises(FileNotFoundError):
            load_trace("/tmp/nonexistent_qa_trace_xyz123.json")

    def test_save_result_writes_json(self):
        """save_result must write valid JSON to disk."""
        result = {"avg_ratio": 0.45, "turns_total": 4}
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "result.json"
            save_result(result, output_path)
            assert output_path.exists()
            with output_path.open() as f:
                loaded = json.load(f)
            assert loaded["avg_ratio"] == pytest.approx(0.45, rel=1e-4)

    def test_save_result_creates_parent_dirs(self):
        """save_result must create missing parent directories."""
        result = {"avg_ratio": 0.3}
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = Path(tmpdir) / "sdd" / "baseline" / "result.json"
            save_result(result, nested_path)
            assert nested_path.exists()
