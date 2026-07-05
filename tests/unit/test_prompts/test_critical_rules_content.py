"""T-04, T-13 — critical_rules.md and booking_flow.md content assertions.

RED phase: verifies that R-23, R-24, and 9b-trigger strengthening are present,
and measures token count to ensure budget compliance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SHARED = Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "shared"


def _read(filename: str) -> str:
    return (_SHARED / filename).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T-04a: Slot-Mutation Rule R-23
# ---------------------------------------------------------------------------


def test_r23_primera_accion_present():
    """R-23 must contain 'primera acción' (slot-mutating turns call update_booking first)."""
    content = _read("critical_rules.md")
    assert (
        "primera acción" in content or "primera accion" in content.lower()
    ), "R-23 'primera acción' phrase not found in critical_rules.md"


def test_r23_update_booking_present():
    """R-23 must reference 'update_booking' as the required first tool."""
    content = _read("critical_rules.md")
    assert "update_booking" in content


# ---------------------------------------------------------------------------
# R-45: Returning-customer propose-the-usual (loyal-echo prompt gap)
# ---------------------------------------------------------------------------


def test_r45_returning_customer_propose_usual_present():
    """R-45 must instruct the model to propose 'Servicios habituales' with confirmation.

    Closes the loyal-echo prompt gap: memory is in <customer> but no rule told the
    model to use it for a vague / 'lo de siempre' request.
    """
    content = _read("critical_rules.md")
    assert "[R-45]" in content, "R-45 not found in critical_rules.md"
    assert (
        "Servicios habituales" in content
    ), "R-45 must reference the <customer> 'Servicios habituales' field"
    assert "lo de siempre" in content, "R-45 must cover the 'lo de siempre' phrasing"
    assert (
        "CONFIRMA" in content or "confirma" in content.lower()
    ), "R-45 must require confirmation before update_booking (no silent assume)"


# ---------------------------------------------------------------------------
# T-04b: Numbered-List Stylist Rule R-24
# ---------------------------------------------------------------------------


def test_r24_lista_numerada_present():
    """R-24 must contain 'lista numerada' (stylist_required → numbered list)."""
    content = _read("critical_rules.md")
    assert (
        "lista numerada" in content.lower()
    ), "R-24 'lista numerada' phrase not found in critical_rules.md"


def test_r24_payload_stylists_present():
    """R-24 must reference 'payload.stylists' as the data source."""
    content = _read("critical_rules.md")
    assert (
        "payload.stylists" in content
    ), "R-24 'payload.stylists' reference not found in critical_rules.md"


# ---------------------------------------------------------------------------
# T-04c: 9b-trigger strengthening — DEBE (uppercase imperative)
# ---------------------------------------------------------------------------


def test_9b_trigger_uses_debe_imperative():
    """9b-trigger must use DEBE (uppercase) imperative, not 'debes' lowercase."""
    content = _read("critical_rules.md")
    # Check for uppercase DEBE (imperative form)
    assert "DEBE" in content, "9b-trigger must use imperative 'DEBE' (uppercase) — found neither"


def test_9b_trigger_variant_skip_prohibition():
    """9b-trigger must contain the variant-skip prohibition sentence."""
    content = _read("critical_rules.md")
    # The strengthened rule must prevent skipping variant_required
    assert (
        "variant_required" in content
    ), "9b-trigger must mention 'variant_required' skip prohibition"


# ---------------------------------------------------------------------------
# T-04d: booking_flow.md payload reference
# ---------------------------------------------------------------------------


def test_booking_flow_references_payload_stylists():
    """booking_flow.md stylist section must reference payload.stylists."""
    content = _read("booking_flow.md")
    assert (
        "payload.stylists" in content
    ), "booking_flow.md must reference 'payload.stylists' in stylist section"


# ---------------------------------------------------------------------------
# T-13: Token budget check (measure and verify after R-23/R-24 added)
# ---------------------------------------------------------------------------


def test_critical_rules_token_budget():
    """critical_rules.md must stay within the token budget.

    Budget 4500, matching test_token_budgets.py (the canonical budget table)
    after R-43/R-44 (multi-service PR-2), R-45 (returning-customer
    propose-the-usual), the qa-loop-conversation-quality R26/R27
    dual-condition cross-reference, and the context-coherence R-39
    acknowledgment carve-out (TASK-13, PR-B; actual 4458) landed. Both tests
    enforce the same ceiling.
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
    except ImportError:
        pytest.skip("tiktoken not installed")

    content = _read("critical_rules.md")
    count = len(enc.encode(content))
    assert count <= 4500, f"critical_rules.md exceeds token budget: {count} tokens > 4500 allowed"
