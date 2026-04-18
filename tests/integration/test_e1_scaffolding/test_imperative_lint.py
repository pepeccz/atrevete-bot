"""Integration smoke test: AST imperative-lint over agent/tools/*.py (R9 application).

This test scans the existing agent/tools/ directory using assert_no_imperative_errors.
Pre-existing tool files were written before the ToolResponse contract existed and may
contain imperative verbs in errors=[...] positions. Migrating them is E2 work.

Marked xfail(strict=False) so that:
  - Pre-existing violations → expected failure (x) — not a blocking error.
  - If all tools happen to be clean → unexpected pass (XPASS) is allowed (strict=False).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.core.tool_response import assert_no_imperative_errors

TOOLS_DIR = Path(__file__).parent.parent.parent.parent / "agent" / "tools"


@pytest.mark.xfail(
    strict=False,
    reason="agent/tools/* not yet migrated to ToolResponse in E1; E2 will remove this xfail",
)
def test_ast_lint_on_existing_tools():
    """Assert zero imperative violations across all agent/tools/*.py files.

    Expected to fail in E1 because legacy tools predate the ToolResponse contract.
    """
    tool_files = list(TOOLS_DIR.glob("*.py"))
    assert tool_files, f"No .py files found in {TOOLS_DIR}"

    all_violations: list[str] = []
    for tool_file in tool_files:
        violations = assert_no_imperative_errors(tool_file)
        all_violations.extend(violations)

    assert all_violations == [], (
        f"Found {len(all_violations)} imperative violation(s) in agent/tools/:\n"
        + "\n".join(all_violations)
    )
