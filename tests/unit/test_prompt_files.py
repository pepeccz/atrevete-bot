"""Focused prompt hardening tests for booking UX copy rules."""

from pathlib import Path

import pytest


@pytest.fixture
def prompt_dir():
    """Return the prompts directory path."""
    base = Path(__file__).parent.parent.parent
    return base / "agent" / "prompts"


class TestTokenBudgets:
    """Verify token budget compliance for rewritten shared prompts."""

    def test_identity_md_token_budget(self, prompt_dir):
        content = (prompt_dir / "shared" / "identity.md").read_text()
        assert len(content) // 4 <= 350

    def test_critical_rules_md_token_budget(self, prompt_dir):
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()
        # Updated for booking-ideal-flow-completion: +450 for R-22 expansion + R-26/R-27 (was 1300)
        assert len(content) // 4 <= 2200

    def test_booking_flow_md_token_budget(self, prompt_dir):
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        # Updated for booking-ideal-flow-completion: +800 for Paso 2 slot-first rewrite (was 1400)
        assert len(content) // 4 <= 2700

    def test_booking_flow_orders_date_before_exact_slots(self, prompt_dir):
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()

        step_service = content.index("### Paso 1")
        step_extras = content.index("### Paso 2")
        step_stylist = content.index("### Paso 3")
        step_date = content.index("### Paso 4")
        step_name = content.index("### Paso 5")

        assert step_service < step_extras < step_stylist < step_date < step_name
        assert "hasta 3 huecos" in content

    def test_booking_flow_limits_emoji_usage(self, prompt_dir):
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()

        assert "Emojis con mucha moderación" in content


class TestClosedWorldGrounding:
    """Verify rule 13 (closed-world grounding) in critical_rules.md."""

    def test_rule_13_present_in_critical_rules(self, prompt_dir):
        """critical_rules.md must contain rule 13 about closed-world grounding."""
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()

        # Check for rule 13
        assert "13." in content, "Rule 13 not found in critical_rules.md"

        # Check for key phrases
        assert "fuente cerrada" in content, "Rule 13 missing 'fuente cerrada'"
        assert "<customer>" in content, "Rule 13 missing XML tag names"
        assert "<upcoming_appointments>" in content, "Rule 13 missing XML tag names"
        assert "<catalog>" in content, "Rule 13 missing XML tag names"
        assert "<business_hours>" in content, "Rule 13 missing XML tag names"


class TestPromptContracts:
    """Verify prompt contracts from audit — prevent regressions on date/stylist ambiguity."""

    def test_critical_rules_prohibits_esa_dia(self, prompt_dir):
        """Rule 15 must prohibit 'ese día' expressions."""
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()
        assert "ese día" in content, "Rule 15 missing 'ese día' prohibition"
        assert "Referencias temporales prohibidas" in content, (
            "Rule 15 missing temporal reference rule"
        )

    def test_critical_rules_requires_check_availability_for_availability(self, prompt_dir):
        """Rule 16 must require check_availability before claiming availability."""
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()
        assert "Disponibilidad verificada" in content, "Rule 16 missing verified availability rule"
        assert "check_availability" in content, "Rule 16 must mention check_availability"

    def test_critical_rules_offers_stylist_proxima(self, prompt_dir):
        """Rule 17 must offer 'estilista con disponibilidad más próxima'."""
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()
        assert "Recomendación por proximidad" in content, "Rule 17 missing proximity recommendation"
        assert "disponibilidad más próxima" in content, "Rule 17 must mention stylist opción"

    def test_booking_flow_step3_offers_stylist_proxima(self, prompt_dir):
        """Paso 3 must offer 'estilista con disponibilidad más próxima'."""
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        assert "disponibilidad más próxima" in content, "Paso 3 must offer stylist opción"

    def test_booking_flow_step3_prohibits_affirming_availability(self, prompt_dir):
        """Paso 3 must not affirm availability without checking."""
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        step3_section = content[content.find("### Paso 3") : content.find("### Paso 4")]
        assert "NO afirmes disponibilidad" in step3_section, (
            "Paso 3 must prohibit affirming availability"
        )

    def test_booking_flow_step4_requires_explicit_date(self, prompt_dir):
        """Paso 4 must require a concrete date before mentioning availability."""
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        step4_section = content[content.find("### Paso 4") : content.find("### Paso 5")]
        assert "sin fecha concreta" in step4_section, "Paso 4 must require explicit date"
