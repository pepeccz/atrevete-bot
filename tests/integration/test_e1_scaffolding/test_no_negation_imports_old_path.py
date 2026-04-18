"""
Integration test: assert zero files in the repo import from shared.negation_phrases.

R15 — After C5 hard-rename, NO file may import from the old path.

This test is written BEFORE the rename so it starts RED (two live importers).
After C5 (rename + import updates + deletion), it must go GREEN.

Strategy:
1. Walk all .py files in the repo (excluding venv, __pycache__, node_modules,
   alembic/versions, .git).
2. Parse AST and walk ImportFrom nodes — reject any whose module starts with
   "shared.negation_phrases" or is exactly "shared" with name "negation_phrases".
3. String-search safety net: reject any file whose source text contains the
   literal string "shared.negation_phrases" outside of docstrings/comments.
   Exception: this test file itself is excluded from the string-search pass
   because it defines the banned string as a literal in the test body.
"""

import ast
from pathlib import Path

import pytest

# Repo root — two levels up from tests/integration/test_e1_scaffolding/
REPO_ROOT = Path(__file__).parent.parent.parent.parent

# Directories to skip entirely during the walk.
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "alembic",  # migrations may reference old paths in comments
    "htmlcov",
    ".mypy_cache",
    ".ruff_cache",
}

# This test file itself is excluded from the string-search net (it contains
# the banned string as a test literal).
THIS_FILE = Path(__file__).resolve()


def _should_skip(path: Path) -> bool:
    """Return True if path should be excluded from scanning."""
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    return False


def _iter_py_files(root: Path):
    """Yield all .py files under root, excluding skip dirs."""
    for p in root.rglob("*.py"):
        if not _should_skip(p):
            yield p


def _check_ast_imports(py_file: Path) -> list[str]:
    """Return list of violation strings for shared.negation_phrases imports."""
    violations: list[str] = []
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        # Un-parseable file — skip (ruff/mypy will catch syntax errors)
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Direct: from shared.negation_phrases import ...
            if module == "shared.negation_phrases" or module.startswith(
                "shared.negation_phrases."
            ):
                names = [alias.name for alias in node.names]
                violations.append(
                    f"{py_file}:{node.lineno}: "
                    f"'from {module} import {', '.join(names)}'"
                )
            # Indirect: from shared import negation_phrases
            if module == "shared":
                for alias in node.names:
                    if alias.name == "negation_phrases":
                        violations.append(
                            f"{py_file}:{node.lineno}: "
                            f"'from shared import negation_phrases'"
                        )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "shared.negation_phrases" or alias.name.startswith(
                    "shared.negation_phrases."
                ):
                    violations.append(
                        f"{py_file}:{node.lineno}: "
                        f"'import {alias.name}'"
                    )

    return violations


def _check_string_literals(py_file: Path) -> list[str]:
    """String-search safety net for dynamic importers."""
    if py_file.resolve() == THIS_FILE:
        return []  # exclude self

    violations: list[str] = []
    try:
        lines = py_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return violations

    for lineno, line in enumerate(lines, start=1):
        # Skip comment lines
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if "shared.negation_phrases" in line:
            violations.append(
                f"{py_file}:{lineno}: string reference to 'shared.negation_phrases'"
            )

    return violations


def test_zero_importers_of_shared_negation_phrases():
    """Assert NO .py file in the repo imports from shared.negation_phrases."""
    ast_violations: list[str] = []
    string_violations: list[str] = []

    for py_file in _iter_py_files(REPO_ROOT):
        ast_violations.extend(_check_ast_imports(py_file))
        string_violations.extend(_check_string_literals(py_file))

    all_violations = ast_violations + string_violations
    if all_violations:
        report = "\n".join(all_violations)
        pytest.fail(
            f"Found {len(all_violations)} reference(s) to 'shared.negation_phrases':\n{report}"
        )
