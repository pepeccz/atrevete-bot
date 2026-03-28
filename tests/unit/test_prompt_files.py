"""
Test suite for prompt hardening constraints.

Verifies:
- Token budget compliance for general.md and escalation.md
- Dialect consistency (voseo → tuteo in greeting.md)
- Phantom reference elimination (glossary.md, recovery.md references)
- Closed-world grounding rule (rule 13 in critical_rules.md)
"""

import pytest
from pathlib import Path


@pytest.fixture
def prompt_dir():
    """Return the prompts directory path."""
    base = Path(__file__).parent.parent.parent
    return base / "agent" / "prompts"


class TestTokenBudgets:
    """Verify token budget compliance for rewritten prompts."""

    def test_general_md_token_budget(self, prompt_dir):
        """general.md must be ≤ 900 tokens (~3,600 chars)."""
        content = (prompt_dir / "modes" / "general.md").read_text()
        char_count = len(content)
        token_estimate = char_count // 4

        assert token_estimate <= 900, (
            f"general.md exceeds budget: {token_estimate} tokens "
            f"({char_count} chars, limit ~3,600 chars)"
        )

    def test_escalation_md_token_budget(self, prompt_dir):
        """escalation.md must be ≤ 700 tokens (~2,800 chars)."""
        content = (prompt_dir / "modes" / "escalation.md").read_text()
        char_count = len(content)
        token_estimate = char_count // 4

        assert token_estimate <= 700, (
            f"escalation.md exceeds budget: {token_estimate} tokens "
            f"({char_count} chars, limit ~2,800 chars)"
        )


class TestDialectConsistency:
    """Verify voseo → tuteo conversion in greeting.md."""

    def test_no_voseo_imperatives_in_greeting(self, prompt_dir):
        """greeting.md must have no voseo imperatives."""
        content = (prompt_dir / "modes" / "greeting.md").read_text()

        voseo_patterns = [
            "Usá",
            "Ofrecé",
            "Saludá",
            "respondé",
            "facilitá",
            "Mantené",
        ]

        found = []
        for pattern in voseo_patterns:
            if pattern in content:
                found.append(pattern)

        assert not found, f"Found voseo imperatives in greeting.md: {found}"


class TestPhantomReferences:
    """Verify elimination of phantom references (glossary.md, recovery.md)."""

    def test_no_glossary_reference_in_general(self, prompt_dir):
        """general.md must not reference shared/glossary.md."""
        content = (prompt_dir / "modes" / "general.md").read_text()
        assert "glossary.md" not in content, "general.md still references glossary.md"

    def test_no_recovery_reference_in_escalation(self, prompt_dir):
        """escalation.md must not reference legacy/recovery.md."""
        content = (prompt_dir / "modes" / "escalation.md").read_text()
        assert "recovery.md" not in content, "escalation.md still references recovery.md"


class TestClosedWorldGrounding:
    """Verify rule 13 (closed-world grounding) in critical_rules.md."""

    def test_rule_13_present_in_critical_rules(self, prompt_dir):
        """critical_rules.md must contain rule 13 about closed-world grounding."""
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()

        # Check for rule 13
        assert "13." in content, "Rule 13 not found in critical_rules.md"

        # Check for key phrases
        assert "fuente cerrada" in content, "Rule 13 missing 'fuente cerrada'"
        assert "<available_stylists>" in content, "Rule 13 missing XML tag names"
        assert "<offered_slots>" in content, "Rule 13 missing XML tag names"
