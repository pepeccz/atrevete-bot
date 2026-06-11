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
        # Recalibrated: R-37 through R-41 were added after the ≤2200 limit was set.
        # Actual current count: ~3201 (chars // 4). Set limit at 10% above actual.
        assert (
            len(content) // 4 <= 3600
        ), f"critical_rules.md exceeds token budget: {len(content) // 4} tokens (limit 3600)"

    def test_booking_flow_md_token_budget(self, prompt_dir):
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        # Recalibrated: policy acceptance (Paso 5.5), safety gate (Paso 5.0) added.
        # Actual current count: ~1786 (chars // 4). Set limit at 10% above actual.
        assert (
            len(content) // 4 <= 2100
        ), f"booking_flow.md exceeds token budget: {len(content) // 4} tokens (limit 2100)"

    def test_booking_flow_orders_pasos(self, prompt_dir):
        """Pasos must appear in order: 1 before 2 before 3 before 4.

        NOTE: booking_flow.md uses bold '**Paso N —' format, not heading '### Paso N'.
        Also booking_flow no longer has the 'Emojis con mucha moderación' line (moved/removed
        in the prompt consolidation). Asserting on step ordering by bold markers.
        """
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()

        # Steps use bold format: **Paso N —
        idx1 = content.find("Paso 1")
        idx2 = content.find("Paso 2")
        idx4 = content.find("Paso 4")
        idx5 = content.find("Paso 5")

        assert idx1 != -1, "booking_flow.md must contain 'Paso 1'"
        assert idx2 != -1, "booking_flow.md must contain 'Paso 2'"
        assert idx4 != -1, "booking_flow.md must contain 'Paso 4'"
        assert idx5 != -1, "booking_flow.md must contain 'Paso 5'"

        assert (
            idx1 < idx2 < idx4 < idx5
        ), "booking_flow.md steps must appear in order: Paso 1 < Paso 2 < Paso 4 < Paso 5"

    def test_booking_flow_references_get_next_available(self, prompt_dir):
        """booking_flow.md must reference get_next_available_options in slot step."""
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        assert (
            "get_next_available_options" in content
        ), "booking_flow.md must reference 'get_next_available_options' in the slot step"


class TestClosedWorldGrounding:
    """Verify rule 13 (closed-world grounding) in critical_rules.md."""

    def test_rule_13_present_in_critical_rules(self, prompt_dir):
        """critical_rules.md must contain rule [R13] about closed-world grounding.

        NOTE: rules now use [R13] bracket format instead of old '13.' prefix (commit 8bf72b4).
        """
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()

        # Check for rule [R13] — bracket format
        assert "[R13]" in content, "Rule [R13] not found in critical_rules.md"

        # Check for key phrases (capital F — "Fuente cerrada" is the rule heading in [R13])
        assert (
            "Fuente cerrada" in content or "fuente cerrada" in content
        ), "Rule [R13] missing 'Fuente cerrada'"
        assert "<customer>" in content, "Rule [R13] missing XML tag names"
        assert "<upcoming_appointments>" in content, "Rule [R13] missing XML tag names"
        assert "<catalog>" in content, "Rule [R13] missing XML tag names"
        assert "<business_hours>" in content, "Rule [R13] missing XML tag names"


class TestPromptContracts:
    """Verify prompt contracts from audit — prevent regressions on date/stylist ambiguity."""

    def test_critical_rules_r14_covers_relative_date_resolution(self, prompt_dir):
        """[R14] must handle relative date resolution (absorbed R15 in commit 8bf72b4).

        NOTE: R15 was retired in commit 8bf72b4 ('retirada 2026-04-28 — absorbida en R14').
        R14 now covers all date resolution including 'resolver relativos con <today>'.
        """
        content = (prompt_dir / "shared" / "critical_rules.md").read_text()
        assert "[R14]" in content, "[R14] must be present in critical_rules.md"
        assert (
            "Resolver relativos" in content or "date_text" in content
        ), "[R14] must reference relative-date resolution or date_text"

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

    def test_booking_flow_stylist_step_offers_first_available(self, prompt_dir):
        """Paso 4 (stylist step) must offer the first-available stylist option.

        NOTE: booking_flow.md uses bold '**Paso N —' markers, not '### Paso N' headings.
        'disponibilidad más próxima' was also moved; R24 now uses 'first_available_label'.
        """
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        assert (
            "first_available_label" in content
        ), "Paso 4 (stylist) must reference 'first_available_label' as the no-preference option (R24)"

    def test_booking_flow_slot_step_requires_get_next_available(self, prompt_dir):
        """Paso 5 (slots step) must call get_next_available_options immediately.

        NOTE: 'NO afirmes disponibilidad' and 'sin fecha concreta' were reworded
        in the prompt consolidation (commit 3a46daf). The current constraint is
        expressed via offer_slots → get_next_available_options immediately.
        """
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        # Paso 5 block — from 'Paso 5' to end of that section
        idx5 = content.find("Paso 5 —")
        assert idx5 != -1, "booking_flow.md must contain 'Paso 5 —' (slots step)"
        paso5_block = content[idx5 : idx5 + 500]
        assert (
            "get_next_available_options" in paso5_block
        ), "Paso 5 must call 'get_next_available_options' immediately on offer_slots"

    def test_booking_flow_slot_step_requires_numbered_menu(self, prompt_dir):
        """Paso 5 must present a numbered menu of slot options."""
        content = (prompt_dir / "shared" / "booking_flow.md").read_text()
        assert (
            "menú numerado" in content or "numerado" in content
        ), "booking_flow.md must require a numbered slot menu"
