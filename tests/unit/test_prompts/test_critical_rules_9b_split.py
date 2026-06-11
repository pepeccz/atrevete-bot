"""Tests that rule 9b in critical_rules.md uses the [R9b] consolidated format."""

from __future__ import annotations

from pathlib import Path

_FILE = (
    Path(__file__).parent.parent.parent.parent
    / "agent"
    / "prompts"
    / "shared"
    / "critical_rules.md"
)


def _content() -> str:
    return _FILE.read_text(encoding="utf-8")


def test_rule_9b_has_trigger_label() -> None:
    """[R9b] is the consolidated label replacing the old 9b-trigger/9b-response split."""
    assert "[R9b]" in _content(), "critical_rules.md must contain '[R9b]'"


def test_rule_9b_has_exception_clause() -> None:
    """[R9b] must contain the Excepción clause (absorbed what was 9b-response)."""
    assert "Excepción" in _content(), "critical_rules.md [R9b] must contain 'Excepción' clause"


def test_rule_9b_trigger_cites_peinado() -> None:
    assert "peinado" in _content().lower(), "[R9b] must mention 'peinado' variant example"


def test_rule_9b_trigger_cites_peinado_largo() -> None:
    """R9b example references Peinado Largo (replaced recogido/semirecogido in v2)."""
    assert "Peinado Largo" in _content(), "[R9b] must mention 'Peinado Largo' variant"


def test_rule_9b_trigger_cites_moldeado_extra() -> None:
    """R9b example references Moldeado Extra (replaced semirecogido in v2)."""
    assert "Moldeado Extra" in _content(), "[R9b] must mention 'Moldeado Extra' variant"
