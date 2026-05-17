"""Measure LLM prompt-cache hit rate from a QA conversation trace.

Standalone script. Reads a trace JSON produced by the QA harness
(same format as tests/e2e/qa_booking_complete_run.py), extracts
``cached_tokens`` and ``prompt_tokens`` per turn from
``response_metadata.token_usage``, computes per-turn ratios, and
saves a summary JSON.

Usage::

    python scripts/measure_cache_hit_rate.py \\
        --scenario tests/qa/conversations/baseline_booking_flow.json \\
        --output sdd/state-first-booking/baseline-cache-hit.json

Output JSON schema::

    {
        "scenario": "<path>",
        "turns": {
            "0": {"cached_tokens": int, "prompt_tokens": int, "ratio": float},
            "1": {...},
            ...
        },
        "avg_ratio": float,
        "turns_with_data": int,
        "turns_total": int,
        "note": "..."
    }

Ratio = cached_tokens / prompt_tokens.
If prompt_tokens == 0 for a turn, that turn is excluded from the average.

Token fields location in trace:
  trace["turns"][i]["raw_response"]["token_usage"]
    → {"prompt_tokens": int, "cached_tokens": int, "completion_tokens": int}

If the trace does not contain token_usage (older format or live run not yet
done), the script emits ratio=null and avg_ratio=null with a note explaining
the data is not available yet.

state-first-booking — Post-change measurement (T5.1 / T5.2)
------------------------------------------------------------
Run ON pepe@server with ENABLE_STATUS_LINE_MIDDLEWARE=True (Batch 5 gate).
Docker and OpenRouter must be running for real token_usage data.

Exact command to run on server::

    cd /home/pepe/Proyectos/atrevete-bot
    ENABLE_STATUS_LINE_MIDDLEWARE=True \\
        python scripts/measure_cache_hit_rate.py \\
        --scenario tests/qa/conversations/baseline_booking_flow.json \\
        --output sdd/state-first-booking/post-cache-hit.json

Expected output file: sdd/state-first-booking/post-cache-hit.json
Expected format: same JSON schema as above, with avg_ratio != null.

Gate T5.2 (go/no-go for Batch 6):
  - Retrieve baseline avg_ratio from engram topic: sdd/state-first-booking/baseline-cache-hit
  - Retrieve post-change avg_ratio from sdd/state-first-booking/post-cache-hit.json
  - delta = abs(avg_ratio_post - avg_ratio_pre)
  - If delta <= 0.05 (5 percentage points): GATE PASSED → proceed to Batch 6
  - If delta > 0.05: STOP → investigate before flipping flag
    (likely cause: _build_dynamic_context changed SystemMessages, invalidating cache)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Core extraction logic — pure functions for testability
# ---------------------------------------------------------------------------


def extract_turn_token_usage(turn: dict[str, Any]) -> dict[str, int | None]:
    """Extract token usage from a single turn dict.

    Supports multiple locations where token data can appear in a QA trace:
    1. turn["raw_response"]["token_usage"] — direct OpenAI-style metadata
    2. turn["raw_response"]["usage_metadata"] — LangChain canonical shape
    3. turn["token_usage"] — top-level shortcut (future format)

    Returns dict with keys: ``cached_tokens``, ``prompt_tokens``,
    ``completion_tokens``. Values are int or None when unavailable.
    """
    raw = turn.get("raw_response") or {}

    # Attempt 1: OpenAI-style token_usage
    token_usage = raw.get("token_usage")
    if isinstance(token_usage, dict):
        return {
            "cached_tokens": _int_or_none(token_usage.get("cached_tokens")),
            "prompt_tokens": _int_or_none(token_usage.get("prompt_tokens")),
            "completion_tokens": _int_or_none(token_usage.get("completion_tokens")),
        }

    # Attempt 2: LangChain usage_metadata
    usage_meta = raw.get("usage_metadata")
    if isinstance(usage_meta, dict):
        return {
            "cached_tokens": _int_or_none(
                usage_meta.get("input_token_details", {}).get("cache_read")
                or usage_meta.get("cached_tokens")
            ),
            "prompt_tokens": _int_or_none(usage_meta.get("input_tokens")),
            "completion_tokens": _int_or_none(usage_meta.get("output_tokens")),
        }

    # Attempt 3: top-level token_usage in turn
    top_usage = turn.get("token_usage")
    if isinstance(top_usage, dict):
        return {
            "cached_tokens": _int_or_none(top_usage.get("cached_tokens")),
            "prompt_tokens": _int_or_none(top_usage.get("prompt_tokens")),
            "completion_tokens": _int_or_none(top_usage.get("completion_tokens")),
        }

    return {"cached_tokens": None, "prompt_tokens": None, "completion_tokens": None}


def compute_turn_ratio(usage: dict[str, int | None]) -> float | None:
    """Compute cached_tokens / prompt_tokens ratio for one turn.

    Returns None when prompt_tokens is 0 or unavailable (division would be
    undefined or meaningless).
    """
    cached = usage.get("cached_tokens")
    prompt = usage.get("prompt_tokens")
    if cached is None or prompt is None or prompt == 0:
        return None
    return round(cached / prompt, 4)


def compute_cache_hit_rate(
    trace: dict[str, Any],
) -> dict[str, Any]:
    """Compute per-turn and average cache hit rate from a QA trace.

    Args:
        trace: Full trace dict as produced by QA harness run scripts.

    Returns:
        Summary dict with per-turn breakdown and ``avg_ratio``.
    """
    turns_raw: list[dict] = trace.get("turns") or []

    per_turn: dict[str, dict] = {}
    ratios_valid: list[float] = []

    for i, turn in enumerate(turns_raw):
        usage = extract_turn_token_usage(turn)
        ratio = compute_turn_ratio(usage)
        per_turn[str(i)] = {
            "turn_number": turn.get("turn_number", i + 1),
            "cached_tokens": usage["cached_tokens"],
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "ratio": ratio,
        }
        if ratio is not None:
            ratios_valid.append(ratio)

    avg_ratio: float | None = None
    note = ""
    if ratios_valid:
        avg_ratio = round(sum(ratios_valid) / len(ratios_valid), 4)
        note = f"{len(ratios_valid)}/{len(turns_raw)} turns have token data"
    else:
        note = (
            "No token_usage data found in trace. "
            "Run the QA scenario against a live agent with OpenRouter to get real cached_tokens."
        )

    return {
        "scenario": trace.get("scenario_id", "unknown"),
        "conversation_id": trace.get("conversation_id", "unknown"),
        "turns": per_turn,
        "avg_ratio": avg_ratio,
        "turns_with_data": len(ratios_valid),
        "turns_total": len(turns_raw),
        "note": note,
    }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _int_or_none(v: Any) -> int | None:
    """Convert value to int or return None on failure."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def load_trace(scenario_path: str | Path) -> dict[str, Any]:
    """Load a QA trace JSON from disk."""
    path = Path(scenario_path)
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_result(result: dict[str, Any], output_path: str | Path) -> None:
    """Save computed cache hit rate result to disk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="measure_cache_hit_rate",
        description=(
            "Measure prompt-cache hit rate from a QA conversation trace JSON. "
            "Extracts cached_tokens/prompt_tokens per turn and computes the average."
        ),
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="Path to QA trace JSON (e.g. tests/qa/conversations/baseline_booking_flow.json)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for the result JSON (e.g. sdd/state-first-booking/baseline-cache-hit.json)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress stdout summary (only write output file)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        trace = load_trace(args.scenario)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON in scenario file: {exc}", file=sys.stderr)
        return 1

    result = compute_cache_hit_rate(trace)
    result["scenario_path"] = str(args.scenario)

    save_result(result, args.output)

    if not args.quiet:
        print(f"Scenario: {result['scenario']}")
        print(f"Conversation ID: {result['conversation_id']}")
        print(f"Turns total: {result['turns_total']}")
        print(f"Turns with token data: {result['turns_with_data']}")
        print(f"Avg cache hit rate: {result['avg_ratio']}")
        print(f"Note: {result['note']}")
        print(f"\nOutput saved to: {args.output}")

        if result["avg_ratio"] is not None:
            print("\nPer-turn breakdown:")
            for turn_key, turn_data in result["turns"].items():
                ratio_str = (
                    f"{turn_data['ratio']:.2%}" if turn_data["ratio"] is not None else "N/A"
                )
                print(
                    f"  Turn {turn_data['turn_number']}: "
                    f"cached={turn_data['cached_tokens']} "
                    f"prompt={turn_data['prompt_tokens']} "
                    f"ratio={ratio_str}"
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())
