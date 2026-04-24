"""Tests that critical_rules.md cites all required XML tag names verbatim."""
from __future__ import annotations

from pathlib import Path

_FILE = (
    Path(__file__).parent.parent.parent.parent
    / "agent" / "prompts" / "shared" / "critical_rules.md"
)

REQUIRED_TAGS = [
    "<customer>",
    "<upcoming_appointments>",
    "<catalog>",
    "<business_hours>",
]


def test_rules_cite_every_tag() -> None:
    content = _FILE.read_text(encoding="utf-8")
    missing = [tag for tag in REQUIRED_TAGS if tag not in content]
    assert not missing, (
        f"critical_rules.md is missing XML tag citations: {missing}"
    )
