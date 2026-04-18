"""Tests for agent.core.status_line — pre-turn HumanMessage builder.

Covers R10 (HumanMessage return), R11 (determinism + no state mutation),
R12 (≤600-char budget on max-populated state), R13 (no state_delivery import,
state_delivery.py hash guard).
"""
from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

import pytest

# ── State-delivery SHA-256 guard constant ─────────────────────────────────────
# Computed at C4 application time (2026-04-18) on feat/architecture-migration-e1.
# If this test breaks, it means state_delivery.py was modified — which is
# forbidden in E1 per R13 and G8 reconciliation.
_STATE_DELIVERY_SHA256 = "32686536e4de1d91516bc903e7f34fb25f40f746e016551779ed2e88b683751e"

_STATE_DELIVERY_PATH = Path(__file__).parents[3] / "agent" / "core" / "state_delivery.py"
_STATUS_LINE_PATH = Path(__file__).parents[3] / "agent" / "core" / "status_line.py"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def minimal_state() -> dict:
    """Minimal valid state — only top-level keys that status_line reads via .get()."""
    return {}


@pytest.fixture()
def typical_state() -> dict:
    return {
        "current_mode": "BOOKING",
        "customer_first_name": "Valentina",
        "booking_context": {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maite",
            "selected_slot": {"start_time": "10:00"},
            "_booking_completed": False,
            "_confirmation_shown": False,
            "notes_asked": False,
            "add_more_asked": False,
        },
    }


@pytest.fixture()
def max_populated_state() -> dict:
    """Deliberately oversized state to stress the 600-char budget."""
    long_name = "X" * 200
    many_services = [f"Servicio Extra {i}" for i in range(10)]
    return {
        "current_mode": "BOOKING",
        "customer_first_name": long_name,
        "booking_context": {
            "last_services": many_services,
            "last_stylist": "Valentina Extraordinaria Longname",
            "selected_slot": {"start_time": "14:30"},
            "_booking_completed": True,
            "_confirmation_shown": True,
            "notes_asked": True,
            "add_more_asked": True,
            "extra_nested": {"deep": "data", "more": "things" * 20},
        },
    }


# ── C4.1: HumanMessage return type ───────────────────────────────────────────


def test_returns_humanmessage_instance(minimal_state):
    from langchain_core.messages import HumanMessage

    from agent.core.status_line import build_status_line

    result = build_status_line(minimal_state)
    assert isinstance(result, HumanMessage)
    assert isinstance(result.content, str)
    assert len(result.content) > 0


# ── C4.2: Determinism + no state mutation ────────────────────────────────────


def test_two_calls_same_state_produce_identical_content(typical_state):
    from agent.core.status_line import build_status_line

    snapshot_before = copy.deepcopy(typical_state)

    result1 = build_status_line(typical_state)
    result2 = build_status_line(typical_state)

    assert result1.content == result2.content, "build_status_line must be deterministic"

    snapshot_after = copy.deepcopy(typical_state)
    assert snapshot_before == snapshot_after, "build_status_line must not mutate state"


# ── C4.3: 600-char budget ────────────────────────────────────────────────────


def test_max_populated_state_within_600_chars(max_populated_state):
    from agent.core.status_line import MAX_CONTENT_CHARS, build_status_line

    result = build_status_line(max_populated_state)
    assert len(result.content) <= MAX_CONTENT_CHARS, (
        f"content length {len(result.content)} exceeds {MAX_CONTENT_CHARS}-char budget"
    )


# ── C4.4: No state_delivery import in status_line (AST lint) ─────────────────


def test_no_state_delivery_import_in_status_line():
    source = _STATUS_LINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_STATUS_LINE_PATH))

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "state_delivery" in alias.name:
                    violations.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "state_delivery" in module:
                violations.append(f"line {node.lineno}: from {module} import ...")

    assert violations == [], (
        "status_line.py MUST NOT import state_delivery. Found:\n" + "\n".join(violations)
    )


# ── C4.5: state_delivery.py SHA-256 guard ────────────────────────────────────


def test_state_delivery_file_unmodified():
    """Verify state_delivery.py has not drifted from its E1 baseline hash.

    This test locks the G8 invariant: state_delivery.py is ORTHOGONAL to
    status_line.py and MUST NOT be touched in E1.
    """
    content = _STATE_DELIVERY_PATH.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    assert actual_hash == _STATE_DELIVERY_SHA256, (
        f"agent/core/state_delivery.py was modified (E1 R13 violation).\n"
        f"  Expected SHA-256: {_STATE_DELIVERY_SHA256}\n"
        f"  Actual  SHA-256: {actual_hash}\n"
        "Update _STATE_DELIVERY_SHA256 only if the change is intentional and "
        "post-E1 (E2+)."
    )
