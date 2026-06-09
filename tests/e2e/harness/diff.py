"""CLI utility to compare two QA run directories and produce a diff report.

Usage:
    python tests/e2e/harness/diff.py --base RUN_DIR --head RUN_DIR [--out diff.md]

Reads {scenario_id}.json from each directory, compares:
- outcome
- bugs count
- tool_calls
- db_delta

Produces a Markdown table to stdout (or --out file) with columns:
Scenario | Base outcome | Head outcome | Δ bugs | Δ tools | Δ DB | Verdict
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_run_files(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all {scenario_id}.json files from a run directory.

    Returns a dict mapping scenario_id → parsed JSON content.
    """
    results: dict[str, dict[str, Any]] = {}
    for path in sorted(run_dir.glob("*.json")):
        # Skip trace files (scenario_id_traces.json pattern)
        if path.stem.endswith("_traces"):
            continue
        # Skip audit.md and similar non-scenario files
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            scenario_id = path.stem
            results[scenario_id] = data
    return results


def _count_tool_calls(run: dict[str, Any]) -> int:
    """Count total tool calls from a run dict."""
    tool_calls = run.get("tool_calls", []) or run.get("tool_evidence", [])
    return len(tool_calls)


def _count_bugs(run: dict[str, Any]) -> int:
    """Count bugs from a run dict."""
    return len(run.get("bugs", []) or [])


def _db_delta_summary(run: dict[str, Any]) -> str:
    """Summarize DB delta from a run dict."""
    delta = run.get("db_delta", {})
    if not delta:
        return "∅"
    parts = []
    for key, val in delta.items():
        if val not in (0, None, {}, []):
            parts.append(f"{key}={val}")
    return ", ".join(parts) if parts else "∅"


def _verdict(base_outcome: str, head_outcome: str, delta_bugs: int) -> str:
    """Determine regression verdict."""
    if base_outcome == head_outcome and delta_bugs <= 0:
        return "OK"
    if head_outcome != base_outcome:
        return "REGRESSED"
    if delta_bugs > 0:
        return "DEGRADED"
    return "OK"


def build_diff_table(base_dir: Path, head_dir: Path) -> str:
    """Build a Markdown diff table comparing two run directories.

    Returns the Markdown table as a string.
    """
    base_runs = _load_run_files(base_dir)
    head_runs = _load_run_files(head_dir)

    all_ids = sorted(set(base_runs.keys()) | set(head_runs.keys()))

    if not all_ids:
        return "_No scenario result files found in either run directory._\n"

    rows = [
        "| Scenario | Base outcome | Head outcome | Δ bugs | Δ tools | Δ DB | Verdict |",
        "|----------|-------------|-------------|--------|---------|------|---------|",
    ]

    for scenario_id in all_ids:
        base = base_runs.get(scenario_id)
        head = head_runs.get(scenario_id)

        base_outcome = base.get("outcome", "missing") if base else "missing"
        head_outcome = head.get("outcome", "missing") if head else "missing"

        base_bugs = _count_bugs(base) if base else 0
        head_bugs = _count_bugs(head) if head else 0
        delta_bugs = head_bugs - base_bugs
        delta_bugs_str = f"+{delta_bugs}" if delta_bugs > 0 else str(delta_bugs)

        base_tools = _count_tool_calls(base) if base else 0
        head_tools = _count_tool_calls(head) if head else 0
        delta_tools = head_tools - base_tools
        delta_tools_str = f"+{delta_tools}" if delta_tools > 0 else str(delta_tools)

        base_db = _db_delta_summary(base) if base else "∅"
        head_db = _db_delta_summary(head) if head else "∅"
        delta_db = head_db if head_db != base_db else "="

        verdict = _verdict(base_outcome, head_outcome, delta_bugs)

        rows.append(
            f"| {scenario_id} | {base_outcome} | {head_outcome} "
            f"| {delta_bugs_str} | {delta_tools_str} | {delta_db} | {verdict} |"
        )

    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two QA run directories and produce a diff report."
    )
    parser.add_argument("--base", required=True, help="Base run directory path")
    parser.add_argument("--head", required=True, help="Head run directory path")
    parser.add_argument(
        "--out",
        default=None,
        help="Output Markdown file path (default: stdout)",
    )
    args = parser.parse_args()

    base_dir = Path(args.base)
    head_dir = Path(args.head)

    if not base_dir.is_dir():
        print(f"[diff] ERROR: base directory not found: {base_dir}", file=sys.stderr)
        sys.exit(1)
    if not head_dir.is_dir():
        print(f"[diff] ERROR: head directory not found: {head_dir}", file=sys.stderr)
        sys.exit(1)

    table = build_diff_table(base_dir, head_dir)

    if args.out:
        Path(args.out).write_text(table, encoding="utf-8")
        print(f"[diff] Wrote diff report to {args.out}", file=sys.stderr)
    else:
        print(table)


if __name__ == "__main__":
    main()
