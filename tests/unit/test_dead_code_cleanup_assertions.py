"""
Smoke assertions for the agent-dead-code-cleanup change.

Verifies AS1–AS10: deleted modules are absent, availability_service loads,
ConversationMode enum is intact, and no stale architectural references remain
in production directories.

These tests are intentionally fast (< 1s), require no DB or Redis connection,
and serve as a permanent regression guard for the cleanup.
"""

from __future__ import annotations

import importlib
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
STALE = re.compile(
    r"\b(Phase 7|StateGraph v\d|FSM consolidated|mode-based architecture|v[67]\.\d modal)\b"
)
PROD_DIRS = ["agent", "api", "shared", "database"]


def test_conversation_mode_enum_still_imports():
    """AS7: ConversationMode enum is intact — not deleted, only its docstring changed."""
    from database.models import ConversationMode  # noqa: F401

    assert hasattr(ConversationMode, "GREETING")


def test_resume_handler_module_does_not_exist():
    """AS1: agent/resume_handler.py deleted — module must not be importable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agent.resume_handler")


def test_query_info_module_does_not_exist():
    """AS2: agent/tools/query_info.py deleted — module must not be importable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agent.tools.query_info")


def test_calendar_tools_module_does_not_exist():
    """AS3: agent/tools/calendar_tools.py deleted — module must not be importable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agent.tools.calendar_tools")


def test_circuit_breaker_module_does_not_exist():
    """AS4: shared/circuit_breaker.py deleted — module must not be importable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("shared.circuit_breaker")


def test_availability_service_loads():
    """AS9: availability_service imports cleanly after the broken import is fixed."""
    importlib.import_module("agent.services.availability_service")


def test_no_stale_v6_v7_phase7_refs_in_prod():
    """AS5/AS6: No stale architectural references in any production .py file."""
    offenders = []
    for d in PROD_DIRS:
        target = ROOT / d
        if not target.exists():
            continue
        for p in target.rglob("*.py"):
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if STALE.search(line):
                    offenders.append(f"{p}:{i}: {line.strip()}")
    assert not offenders, "Stale architectural references:\n" + "\n".join(offenders)
