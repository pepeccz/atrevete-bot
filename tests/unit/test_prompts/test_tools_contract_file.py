"""Structural tests for agent/prompts/shared/tools_contract.md."""
from __future__ import annotations

from pathlib import Path

import pytest

_SHARED = Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "shared"
_FILE = _SHARED / "tools_contract.md"

REQUIRED_TOOLS = [
    "check_availability",
    "get_next_available_options",
    "book",
    "manage_appointments",
    "escalate",
]

REQUIRED_FIELDS = [
    "Cuándo llamar",
    "Nunca llamar",
    "Args requeridos",
    "—",  # purpose encoded as em-dash description on same line as tool name
]


def _content() -> str:
    assert _FILE.exists(), f"tools_contract.md not found at {_FILE}"
    return _FILE.read_text(encoding="utf-8")


def test_tools_contract_covers_all_tools() -> None:
    content = _content()
    for tool in REQUIRED_TOOLS:
        assert tool in content, f"Tool '{tool}' missing from tools_contract.md"


def test_tools_contract_has_required_fields() -> None:
    content = _content()
    for field in REQUIRED_FIELDS:
        assert field in content, f"Field '{field}' missing from tools_contract.md"
