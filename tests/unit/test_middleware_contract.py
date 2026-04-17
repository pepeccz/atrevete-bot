"""AST-based denylist contract test for imperative error_message strings.

Scans ``agent/modes/*.py`` and ``agent/tools/*.py`` for:

  * ``ToolCallRejection(error_message="…")`` keyword-argument string literals
  * ``errors.append("…")`` string-literal arguments

and fails if any extracted string starts with an imperative verb from the
denylist (``Pregunta|Muestra|Llama|Debes``).

The parametrized ``test_detector_catches_synthetic_bad_string`` cases prove that
the detector actually works — they intentionally contain bad strings and are
expected to be flagged.

STRICT TDD note
---------------
RED phase: before Batch B softens the three imperative strings in
``appointment_management_mode.py``, ``test_no_imperative_error_messages``
FAILS (3 violations found).
GREEN phase: after Batch B the production scan PASSES (0 violations).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SCAN_DIRS = [
    _PROJECT_ROOT / "agent" / "modes",
    _PROJECT_ROOT / "agent" / "tools",
]

DENYLIST_RE = re.compile(r"^\s*(Pregunta|Muestra|Llama|Debes)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _literal_string(node: ast.expr) -> str | None:
    """Return the string value of a plain string constant node, else None.

    Only handles ``ast.Constant`` with a ``str`` value.  f-strings
    (``ast.JoinedStr``) and other compound expressions return ``None`` so they
    are excluded from the denylist scan.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_tool_call_rejection(call_node: ast.Call) -> bool:
    """Return True if *call_node* calls ``ToolCallRejection``."""
    func = call_node.func
    if isinstance(func, ast.Name) and func.id == "ToolCallRejection":
        return True
    # Support qualified access: agent.modes.base.ToolCallRejection(...)
    if isinstance(func, ast.Attribute) and func.attr == "ToolCallRejection":
        return True
    return False


def _is_errors_append(call_node: ast.Call) -> bool:
    """Return True if *call_node* is ``errors.append(...)``."""
    func = call_node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "append"
        and isinstance(func.value, ast.Name)
        and func.value.id == "errors"
    )


def _scanned_py_files(scan_dirs: list[Path]) -> list[Path]:
    """Return all ``*.py`` files under the given directories (recursive)."""
    files: list[Path] = []
    for d in scan_dirs:
        if d.is_dir():
            files.extend(sorted(d.rglob("*.py")))
    return files


def _iter_error_messages(
    scan_dirs: list[Path],
) -> Generator[tuple[Path, int, str], None, None]:
    """Yield ``(file, lineno, string_value)`` for each extractable error message.

    Extracted from:
    * ``ToolCallRejection(error_message="<literal>")``
    * ``errors.append("<literal>")``

    Non-literal values (f-strings, variables, concatenations starting with a
    non-string node) are silently skipped.
    """
    for path in _scanned_py_files(scan_dirs):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            # Skip files that cannot be parsed
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # --- ToolCallRejection(error_message=...) ---
            if _is_tool_call_rejection(node):
                for kw in node.keywords:
                    if kw.arg == "error_message":
                        value = _literal_string(kw.value)
                        if value is not None:
                            yield path, node.lineno, value

            # --- errors.append(...) ---
            elif _is_errors_append(node):
                for arg in node.args:
                    value = _literal_string(arg)
                    if value is not None:
                        yield path, node.lineno, value


# ---------------------------------------------------------------------------
# Production scan test
# ---------------------------------------------------------------------------


def test_no_imperative_error_messages() -> None:
    """Production scan: no imperative error_message strings in agent/modes/ or agent/tools/.

    Fails with a descriptive message naming file:line and the offending string
    if any violation is found.
    """
    violations: list[tuple[Path, int, str]] = [
        (p, lineno, s)
        for p, lineno, s in _iter_error_messages(_SCAN_DIRS)
        if DENYLIST_RE.search(s)
    ]

    if violations:
        lines = [
            f"Imperative error_message strings found — these must be rewritten as "
            f"descriptive state (e.g. 'Estado actual: …'):"
        ]
        for path, lineno, s in violations:
            rel = path.relative_to(_PROJECT_ROOT)
            lines.append(f"  {rel}:{lineno}  →  {s!r}")
        pytest.fail("\n".join(lines))


# ---------------------------------------------------------------------------
# Detector positive-case (proves the scanner works)
# ---------------------------------------------------------------------------

_SYNTHETIC_BAD_STRINGS = [
    ("Pregunta al cliente a quién va dirigida esta cita.", "Pregunta"),
    ("Muestra el resumen y pide confirmación.", "Muestra"),
    ("Llama primero a check_availability.", "Llama"),
    ("Debes confirmar antes de cancelar.", "Debes"),
]


@pytest.mark.parametrize(
    "bad_string, stem",
    [(s, stem) for s, stem in _SYNTHETIC_BAD_STRINGS],
    ids=[stem for _, stem in _SYNTHETIC_BAD_STRINGS],
)
def test_detector_catches_synthetic_bad_string(bad_string: str, stem: str) -> None:
    """Prove the denylist regex correctly identifies a known-bad string.

    This is a POSITIVE-case test — the string is intentionally imperative.
    If the regex does NOT match, the detector is broken.
    """
    assert DENYLIST_RE.search(bad_string) is not None, (
        f"Detector failed to flag imperative string starting with {stem!r}: {bad_string!r}"
    )
