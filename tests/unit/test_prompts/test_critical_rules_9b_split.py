"""Tests that rule 9b in critical_rules.md is split into 9b-trigger and 9b-response."""
from __future__ import annotations

from pathlib import Path

_FILE = (
    Path(__file__).parent.parent.parent.parent
    / "agent" / "prompts" / "shared" / "critical_rules.md"
)


def _content() -> str:
    return _FILE.read_text(encoding="utf-8")


def test_rule_9b_has_trigger_label() -> None:
    assert "9b-trigger" in _content(), "critical_rules.md must contain '9b-trigger'"


def test_rule_9b_has_response_label() -> None:
    assert "9b-response" in _content(), "critical_rules.md must contain '9b-response'"


def test_rule_9b_trigger_cites_peinado() -> None:
    assert "peinado" in _content().lower(), "9b-trigger must mention 'peinado' variant example"


def test_rule_9b_trigger_cites_recogido() -> None:
    assert "recogido" in _content().lower(), "9b-trigger must mention 'recogido' variant"


def test_rule_9b_trigger_cites_semirecogido() -> None:
    assert "semirecogido" in _content().lower(), "9b-trigger must mention 'semirecogido' variant"
