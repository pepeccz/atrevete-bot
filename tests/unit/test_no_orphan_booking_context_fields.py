"""
AST orphan lint for BookingContext fields — REQ-3 / Phase 5.

Walks all production Python files under agent/ to detect:
  - ORPHAN WRITERS: fields declared in BOOKING_STATE_AUTHORITY that have zero
    subscript-assignment writes in source (booking_context[k]=, ctx[k]=, patch[k]=).
  - ORPHAN READERS: non-transient fields declared in BOOKING_STATE_AUTHORITY that
    have zero subscript/get reads in source.

Any orphan is a sign that either:
  (a) the registry declares a field that no code actually touches, or
  (b) code was deleted without updating the registry.

Precedent: tests/unit/test_no_direct_booking_context_writes.py
Python 3.11 note: ast.Subscript.slice is the node directly — no ast.Index wrapper.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent
_AGENT_DIR = _REPO_ROOT / "agent"

# Names used as the base of patch-pipeline subscript writes
_WRITE_BASES = frozenset({"booking_context", "ctx", "patch"})

# Names used as the base of subscript reads.
# We use a broad scan: any dict subscript or .get() call anywhere in agent/
# counts as a potential read. This avoids false-positive orphan-reader failures
# when a field is read via local aliases (hints, booking_hints, initial_booking_ctx, etc.).
_READ_BASES: frozenset[str] = frozenset()  # sentinel — means "accept any base"

# Fields that are intentionally never written via subscript (written as dict literal
# keys in resolver return dicts like patch={"confirmed": True}).  We allow-list these
# so the writer check doesn't false-positive on patch-pipeline-style writers.
_DICT_LITERAL_WRITERS = frozenset(
    {
        "confirmed",
        "_confirmation_shown",
        "add_more_asked",
        "selected_slot",
        "last_stylist",
    }
)

# Fields declared as transient or that have zero readers by design (see registry notes).
_KNOWN_ZERO_READERS_OK = frozenset(
    {
        "_suggested_customer_name",  # transient=True; reader is the LLM prompt string, not Python
        "booked_appointment_id",  # declared structurally; zero production writers/readers by design
    }
)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _collect_string_subscript_writes(tree: ast.AST) -> set[str]:
    """Return all string keys written via subscript assignment: base["key"] = ..."""
    written: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign)):
            continue
        targets: list[ast.expr] = (
            node.targets if isinstance(node, ast.Assign) else [node.target]  # type: ignore[list-item]
        )
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            base = target.value
            base_name: str | None = None
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name not in _WRITE_BASES:
                continue
            # Python 3.11+: slice is the node directly
            slice_node = target.slice
            if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                written.add(slice_node.value)
    return written


def _collect_string_subscript_reads(tree: ast.AST) -> set[str]:
    """Return all string keys accessed via any subscript or .get() call in the file.

    We accept any base variable name because BookingContext fields are often read
    through local aliases (hints, booking_hints, initial_booking_ctx, memories, etc.).
    The goal is to detect fields that are NEVER referenced anywhere in agent/ source —
    not to enforce a specific variable name convention.
    """
    read: set[str] = set()
    for node in ast.walk(tree):
        # Pattern 1: any_dict["key"]
        if isinstance(node, ast.Subscript):
            slice_node = node.slice
            if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                read.add(slice_node.value)

        # Pattern 2: any_dict.get("key", ...)
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "get":
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        read.add(arg.value)
    return read


def _collect_dict_literal_keys(tree: ast.AST) -> set[str]:
    """Return all string keys that appear as keys in dict literals (patch={...} style writers)."""
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def _scan_agent_dir() -> tuple[set[str], set[str]]:
    """
    Walk all .py files under agent/ and collect:
      - all_written: fields written via subscript assignment OR dict literal key
      - all_read: fields read via subscript access or .get()
    """
    all_written: set[str] = set()
    all_read: set[str] = set()

    for py_file in _AGENT_DIR.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        all_written |= _collect_string_subscript_writes(tree)
        all_written |= _collect_dict_literal_keys(tree)
        all_read |= _collect_string_subscript_reads(tree)

    return all_written, all_read


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoOrphanBookingContextFields:
    """REQ-3 / Phase 5: every registry field must have at least one writer and reader."""

    @pytest.fixture(scope="class")
    def scan_results(self):
        """Run the AST scan once per class (expensive — hits disk)."""
        return _scan_agent_dir()

    @pytest.fixture(scope="class")
    def registry(self):
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY

        return BOOKING_STATE_AUTHORITY

    def test_no_orphan_writers(self, scan_results, registry) -> None:
        """Every registry field must have at least one write in agent/ source."""
        all_written, _ = scan_results

        orphan_writers = []
        for field in registry:
            # Skip fields that are legitimately written only via dict-literal patches
            # (those are already included in all_written via _collect_dict_literal_keys)
            if field not in all_written and field not in _DICT_LITERAL_WRITERS:
                orphan_writers.append(field)

        assert not orphan_writers, (
            f"Registry fields with ZERO writers in agent/: {orphan_writers}\n"
            "Either add a writer or remove the field from BOOKING_STATE_AUTHORITY."
        )

    def test_no_orphan_readers(self, scan_results, registry) -> None:
        """Every non-transient registry field must have at least one read in agent/ source."""
        _, all_read = scan_results

        orphan_readers = []
        for field, authority in registry.items():
            if authority.get("transient"):
                continue  # transient fields are consumed by the LLM prompt string
            if field in _KNOWN_ZERO_READERS_OK:
                continue
            if field not in all_read:
                orphan_readers.append(field)

        assert not orphan_readers, (
            f"Registry fields with ZERO readers in agent/: {orphan_readers}\n"
            "Either add a reader or mark the field transient=True in BOOKING_STATE_AUTHORITY."
        )

    def test_scan_covers_booking_data_tools(self, scan_results) -> None:
        """Sanity: scan must have found at least the well-known 'last_services' write."""
        all_written, _ = scan_results
        assert (
            "last_services" in all_written
        ), "AST scan did not find 'last_services' write — scanner may be broken."

    def test_scan_covers_grounding_reads(self, scan_results) -> None:
        """Sanity: scan must have found at least the well-known 'confirmed' read in grounding."""
        _, all_read = scan_results
        assert (
            "confirmed" in all_read
        ), "AST scan did not find 'confirmed' read — scanner may be broken."
