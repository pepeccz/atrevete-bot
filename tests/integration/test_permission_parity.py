"""Integration test: backend and frontend permission dicts must be equal.

Verifies SC-PARITY-1 (FR-PERM-4, NFR-6).

The test reads `admin-panel/src/lib/permissions.ts` as text, extracts the
ROLE_PERMISSIONS dict via regex, normalizes both sides to dict[str, set[str]],
and asserts structural equality.

The TS file shape is part of the contract:
  "<role>": new Set([
    "permission:one",
    ...
  ]),
DO NOT change this shape without updating the regex in _parse_ts_role_permissions().
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.permissions import ROLE_PERMISSIONS

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# Repository root is 2 levels up from tests/integration/
_REPO_ROOT = Path(__file__).parent.parent.parent
_TS_PERMISSIONS_PATH = _REPO_ROOT / "admin-panel" / "src" / "lib" / "permissions.ts"


# ---------------------------------------------------------------------------
# TS parser
# ---------------------------------------------------------------------------


def _parse_ts_role_permissions(ts_source: str) -> dict[str, set[str]]:
    """Extract ROLE_PERMISSIONS from the TypeScript source as dict[str, set[str]].

    Expected TS shape (must not change without updating this parser):
      "<role>": new Set([
        "permission:one",
        "permission:two",
      ]),

    Args:
        ts_source: Full text of permissions.ts.

    Returns:
        dict mapping role name → set of permission strings.

    Raises:
        ValueError: if the TS source does not match the expected shape.
    """
    result: dict[str, set[str]] = {}

    # Match each role block: admin: new Set([ ... ]) or "admin": new Set([ ... ])
    role_block_re = re.compile(
        r'"?(admin|stylist)"?\s*:\s*new\s+Set\(\s*\[(.*?)\]\s*\)',
        re.DOTALL,
    )
    for match in role_block_re.finditer(ts_source):
        role = match.group(1)
        block = match.group(2)
        # Extract all quoted strings inside the Set([...])
        perm_re = re.compile(r'"([a-z0-9_:]+)"')
        permissions = set(perm_re.findall(block))
        result[role] = permissions

    if not result:
        raise ValueError(
            f"Could not parse any role blocks from {_TS_PERMISSIONS_PATH}. "
            "Check that the file shape matches the expected format (see docstring)."
        )
    return result


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_backend_and_frontend_permission_dicts_match():
    """SC-PARITY-1: Backend ROLE_PERMISSIONS == frontend permissions.ts dict."""
    if not _TS_PERMISSIONS_PATH.exists():
        pytest.fail(
            f"Frontend permissions file not found: {_TS_PERMISSIONS_PATH}\n"
            "Create admin-panel/src/lib/permissions.ts before running this test."
        )

    ts_source = _TS_PERMISSIONS_PATH.read_text(encoding="utf-8")
    frontend = _parse_ts_role_permissions(ts_source)

    # Normalize backend to dict[str, set[str]] for comparison
    backend = {role: set(perms) for role, perms in ROLE_PERMISSIONS.items()}

    # Compare role keys
    if set(backend.keys()) != set(frontend.keys()):
        pytest.fail(
            f"Role key mismatch:\n"
            f"  Backend roles:  {sorted(backend.keys())}\n"
            f"  Frontend roles: {sorted(frontend.keys())}"
        )

    # Compare permissions per role
    for role in backend:
        backend_perms = backend[role]
        frontend_perms = frontend.get(role, set())

        backend_only = backend_perms - frontend_perms
        frontend_only = frontend_perms - backend_perms

        if backend_only or frontend_only:
            lines = [f"Permission mismatch for role '{role}':"]
            if backend_only:
                lines.append(f"  In backend only:  {sorted(backend_only)}")
            if frontend_only:
                lines.append(f"  In frontend only: {sorted(frontend_only)}")
            pytest.fail("\n".join(lines))


def test_parse_ts_role_permissions_handles_all_roles():
    """Parser extracts both 'admin' and 'stylist' blocks from permissions.ts."""
    if not _TS_PERMISSIONS_PATH.exists():
        pytest.skip(f"Frontend permissions file not found: {_TS_PERMISSIONS_PATH}")

    ts_source = _TS_PERMISSIONS_PATH.read_text(encoding="utf-8")
    parsed = _parse_ts_role_permissions(ts_source)

    assert "admin" in parsed, "Parser failed to extract 'admin' role"
    assert "stylist" in parsed, "Parser failed to extract 'stylist' role"
    assert len(parsed["admin"]) > 0, "Admin permission set is empty"
    assert len(parsed["stylist"]) > 0, "Stylist permission set is empty"
