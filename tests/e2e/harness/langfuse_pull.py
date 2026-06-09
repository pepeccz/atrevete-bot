"""CLI utility to pull Langfuse traces for a QA conversation.

Usage:
    python tests/e2e/harness/langfuse_pull.py --conv-id <UUID> --out <PATH> [--retries 4]

Fetches traces by session_id from Langfuse API, writes a JSON array to --out.
Retries with exponential backoff (2s, 4s, 6s, 8s) to handle async flush delays.
Exits non-zero if no traces found after all retries.

Note: Uses Langfuse SDK 4.x REST API client (langfuse.api.client.LangfuseAPI).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from langfuse.api.client import LangfuseAPI

from shared.config import get_settings


def _trace_to_dict(trace: Any) -> dict[str, Any]:
    """Convert a Langfuse trace object to a JSON-serializable dict."""
    result: dict[str, Any] = {}
    for field in ("id", "name", "input", "output", "timestamp", "session_id", "user_id", "metadata", "tags"):
        val = getattr(trace, field, None)
        if val is not None:
            try:
                # Pydantic models have model_dump(); plain objects just use the value.
                result[field] = val.model_dump() if hasattr(val, "model_dump") else val
            except Exception:
                result[field] = str(val)
    return result


def _observation_to_dict(obs: Any) -> dict[str, Any]:
    """Convert a Langfuse observation to a JSON-serializable dict."""
    result: dict[str, Any] = {}
    for field in ("id", "trace_id", "type", "name", "model", "input", "output", "level", "start_time", "end_time", "version"):
        val = getattr(obs, field, None)
        if val is not None:
            try:
                result[field] = val.model_dump() if hasattr(val, "model_dump") else val
            except Exception:
                result[field] = str(val)
    # Normalise usage field
    usage = getattr(obs, "usage", None)
    if usage is not None:
        result["usage"] = {
            "input": getattr(usage, "input", None),
            "output": getattr(usage, "output", None),
            "total": getattr(usage, "total", None),
        }
    return result


def pull_traces(conv_id: str, out: str, retries: int = 4) -> int:
    """Fetch Langfuse traces for conv_id and write JSON array to out.

    Returns 0 on success, non-zero if no traces found after all retries.
    """
    settings = get_settings()

    client = LangfuseAPI(
        base_url=settings.LANGFUSE_BASE_URL,
        username=settings.LANGFUSE_PUBLIC_KEY,
        password=settings.LANGFUSE_SECRET_KEY,
        x_langfuse_sdk_name="atrevete-qa-harness",
        x_langfuse_sdk_version="1.0.0",
        x_langfuse_public_key=settings.LANGFUSE_PUBLIC_KEY,
    )

    traces: list[Any] = []
    for attempt in range(retries):
        response = client.trace.list(session_id=conv_id, limit=50)
        traces = response.data or []
        if traces:
            break
        if attempt < retries - 1:
            delay = 2 * (attempt + 1)  # 2s, 4s, 6s, ...
            time.sleep(delay)

    if not traces:
        print(
            f"[langfuse_pull] No traces found for session_id={conv_id!r} after {retries} attempt(s).",
            file=sys.stderr,
        )
        return 1

    result: list[dict[str, Any]] = []
    for trace in traces:
        obs_response = client.observations.get_many(trace_id=trace.id, limit=200)
        observations = obs_response.data or []
        result.append(
            {
                "trace": _trace_to_dict(trace),
                "observations": [_observation_to_dict(o) for o in observations],
            }
        )

    Path(out).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(
        f"[langfuse_pull] Wrote {len(result)} trace(s) to {out}",
        file=sys.stderr,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull Langfuse traces for a QA conversation session."
    )
    parser.add_argument("--conv-id", required=True, help="Conversation/session UUID")
    parser.add_argument("--out", required=True, help="Output JSON file path")
    parser.add_argument(
        "--retries",
        type=int,
        default=4,
        help="Number of fetch attempts with exponential backoff (default: 4)",
    )
    args = parser.parse_args()

    exit_code = pull_traces(conv_id=args.conv_id, out=args.out, retries=args.retries)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
