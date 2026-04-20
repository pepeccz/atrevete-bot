#!/usr/bin/env python3
"""AST-based gate: detect direct booking_context mutations outside the patch pipeline.

See spec R6.1 and design §2.3.

Exit codes: 0=clean, 1=violations found, 2=parse error.

Usage:
    python scripts/check_booking_state_writes.py        # scan from repo root
    python scripts/check_booking_state_writes.py --help

The script scans:
    - agent/modes/booking_mode.py
    - agent/tools/booking_data_tools.py
    - infra/resolvers/*.py

It flags any ast.Assign / ast.AugAssign where the target is a subscript of
a local named booking_context / mode_context / ctx.

Allow-listed sites (not flagged):
    - Any assignment inside apply_resolver_patch (patch_pipeline.py is the
      authorized mutation channel; it assigns via a loop, not directly here).
    - The single patch-application loop in _post_tool_result
      (mode_context[key] = val — controlled iteration).
    - Inside _resolve_customer_from_state (informational pre-fills, permitted
      per spec R3.2 exception).
    - Assignments to local 'patch' dict in update_booking tool body
      (patch[k]=v is fine; ctx[k]=v is the violation).
    - Inside clear_slot / None-assignment for cache invalidation
      (ctx.pop(...) — pop is a method call, not subscript assign; not flagged).
    - Selected_slot writes inside _pre_tool_call for slot injection
      (Step A — permitted by spec R4.3; these are arg-injection, not
      flow-control writes; flagged by grep but allow-listed here).

Output format per violation:
    file:line: direct mutation to <target> — use apply_resolver_patch or return patch
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent

# Files to scan
_TARGET_FILES: list[Path] = [
    _REPO_ROOT / "agent" / "modes" / "booking_mode.py",
    _REPO_ROOT / "agent" / "tools" / "booking_data_tools.py",
]

# Add all infra/resolvers/*.py
_RESOLVERS_DIR = _REPO_ROOT / "infra" / "resolvers"
if _RESOLVERS_DIR.exists():
    _TARGET_FILES.extend(sorted(_RESOLVERS_DIR.glob("*.py")))

# Names that trigger inspection when used as a subscript base
_CONTEXT_NAMES = frozenset({"booking_context", "mode_context", "ctx"})

# Functions allowed to do direct context mutations:
#   - apply_resolver_patch: the authorized mutation channel itself
#   - _post_tool_result: applies the patch loop (single mode_context[key]=val iteration)
#   - _resolve_customer_from_state: informational pre-fill (spec R3.2 exception)
#   - _resolve_service_category: async DB cache-write (infrastructure, not flow control)
#   - _pre_tool_call: arg-injection only (Step A slot/notes/customer — spec R4.3)
#     NOTE: B.4 will convert Step A.2 customer_name to inject into tool_args only;
#           until then, _pre_tool_call mutations are permitted by spec.
#   - <module>: top-level constants / defaults (not booking_context mutations)
_ALLOWED_FUNCTIONS = frozenset(
    {
        "apply_resolver_patch",
        "_post_tool_result",
        "_resolve_customer_from_state",
        "_resolve_service_category",
        "_pre_tool_call",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_enclosing_function(node: ast.AST, tree: ast.AST) -> str | None:
    """Return the name of the innermost function/method containing node."""
    # Build parent map
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    current: ast.AST | None = node
    while current is not None:
        current = parents.get(id(current))
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return None


def _is_context_subscript_assign(node: ast.Assign | ast.AugAssign) -> str | None:
    """Return the subscript base name if the assignment target is a context subscript.

    Returns None if this assignment is not a direct context mutation.
    """
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AugAssign):
        targets = [node.target]

    for target in targets:
        if not isinstance(target, ast.Subscript):
            continue
        base = target.value
        if isinstance(base, ast.Name) and base.id in _CONTEXT_NAMES:
            return base.id
        # Also catch self._booking_context[k] or self._mode_context[k]
        if isinstance(base, ast.Attribute) and base.attr in _CONTEXT_NAMES:
            return base.attr
    return None


# ---------------------------------------------------------------------------
# scan() — importable by unit tests
# ---------------------------------------------------------------------------


def scan(root: Path | None = None) -> list[str]:
    """Scan target files for direct booking_context mutations.

    Returns a list of violation strings (empty if clean).
    Each violation is: "file:line: direct mutation to <target> — ..."
    """
    violations: list[str] = []

    for fpath in _TARGET_FILES:
        if not fpath.exists():
            continue
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(fpath))
        except SyntaxError as exc:
            violations.append(f"{fpath}:?: parse error — {exc}")
            continue

        rel = fpath.relative_to(_REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AugAssign)):
                continue
            context_name = _is_context_subscript_assign(node)
            if context_name is None:
                continue

            line = getattr(node, "lineno", "?")
            fn_name = _get_enclosing_function(node, tree)

            # Allow-listed functions — skip
            if fn_name in _ALLOWED_FUNCTIONS:
                continue

            violations.append(
                f"{rel}:{line}: direct mutation to '{context_name}' "
                f"in {fn_name or '<module>'}() — use apply_resolver_patch or return patch"
            )

    return violations


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    violations = scan()
    for v in violations:
        print(v)
    if violations:
        print(f"\n{len(violations)} violation(s) found.", file=sys.stderr)
        return 1
    print("check_booking_state_writes: clean (0 violations)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
