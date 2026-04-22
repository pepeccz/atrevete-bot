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
        assert len(content) // 4 <= 1100

    def test_booking_flow_md_token_budget(self, prompt_dir):
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        assert len(content) // 4 <= 950


class TestDialectConsistency:
    """Verify no-voseo guardrails in shared prompt files."""

    def test_booking_flow_rejects_voseo(self, prompt_dir):
        """The executable booking flow must avoid Rioplatense voseo."""
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()

        voseo_patterns = [
            "Usá",
            "Ofrecé",
            "Saludá",
            "respondé",
            "facilitá",
            "Mantené",
            "querés",
            "podés",
            "decime",
            "contame",
            "mostrá",
            "Preguntá",
            "Seguí",
        ]

        found = []
        for pattern in voseo_patterns:
            if pattern in content:
                found.append(pattern)

        assert not found, f"Found voseo patterns in canonical booking prompts: {found}"


class TestBookingCopyRequirements:
    def test_identity_locks_madrid_tone_and_no_voseo(self, prompt_dir):
        content = (prompt_dir / "shared" / "identity.md").read_text()

        assert "castellano de Madrid" in content
        assert "Nunca uses voseo" in content

    def test_critical_rules_cover_service_labels_and_named_stylist_consent(self, prompt_dir):
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()

        assert "No expongas títulos internos en bruto como `Corte Dama`" in content
        assert "Consentimiento antes de ampliar" in content
        assert "get_next_available_options" in content

    def test_booking_flow_uses_approved_name_and_notes_copy(self, prompt_dir):
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()

        assert "nombre y primer apellido" in content
        assert "¿Algo que tengamos que tener en cuenta en tu cita?" in content

    def test_booking_flow_orders_date_before_exact_slots(self, prompt_dir):
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()

        step_service = content.index("### Paso 1")
        step_extras = content.index("### Paso 2")
        step_stylist = content.index("### Paso 3")
        step_date = content.index("### Paso 4")
        step_name = content.index("### Paso 5")

        assert step_service < step_extras < step_stylist < step_date < step_name
        assert "ofrece hasta 3 huecos concretos" in content

    def test_booking_flow_limits_emoji_usage(self, prompt_dir):
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()

        assert "Usa emojis con mucha moderación" in content


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
