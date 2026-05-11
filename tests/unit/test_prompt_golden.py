"""
Golden content tests for agent/prompts/shared/ files.

These tests assert structural and content invariants on the static prompt
source files. They do NOT require Postgres or Redis — they read the filesystem
only and are safe to run in any environment.

TDD progression:
  T2.1 [RED]   — glossary axis table: 4 rows, no duration row
  T2.2 [RED]   — critical_rules.md contains R-34 canonical phrase
  T2.3 [GREEN] — surgical glossary edit removes duration row + adds footnote
  T2.4 [GREEN] — R-34 appended to critical_rules.md
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "agent" / "prompts"
GLOSSARY_PATH = PROMPTS_DIR / "shared" / "glossary.md"
CRITICAL_RULES_PATH = PROMPTS_DIR / "shared" / "critical_rules.md"


# ---------------------------------------------------------------------------
# REQ-TE-4 / T2.1 — glossary.md axis-mapping table: 4 rows, no duration row
# ---------------------------------------------------------------------------


def test_glossary_axis_table_has_no_duration_row() -> None:
    """T2.1 [RED→GREEN]: The axis-mapping table must NOT contain a duration row.

    After T2.3 removes the `variant (duración)` row, this test passes.
    RED until the surgical glossary edit is applied.
    """
    content = GLOSSARY_PATH.read_text(encoding="utf-8")

    # The duration-axis row must be gone
    assert "variant` (duración)" not in content, (
        "The `variant (duración)` row must be removed from glossary.md "
        "after migration a3b4c5d6e7f8 reclassifies duration-delta services as ADDONs."
    )


def test_glossary_axis_table_surviving_rows_present() -> None:
    """T2.1 companion: the 4 surviving axis rows must still be present after the edit."""
    content = GLOSSARY_PATH.read_text(encoding="utf-8")

    assert (
        "variant` (zona)" in content
    ), "The zona axis row must remain in glossary.md (zone-based variants like Depilación are valid)."
    assert (
        "variant` (longitud)" in content
    ), "The longitud axis row must remain in glossary.md (Peinado Largo is a valid length variant)."
    assert (
        "variant` (formalidad)" in content
    ), "The formalidad axis row must remain in glossary.md (Recogido de Novia is a valid formality variant)."
    assert "audience" in content, "The audience axis row must remain in glossary.md."


def test_glossary_operational_footnote_present() -> None:
    """T2.1 companion: an operational footnote explaining duration=ADDON must be present.

    The footnote prevents future catalog drift by documenting WHY the duration
    axis was removed from the disambiguation table.
    """
    content = GLOSSARY_PATH.read_text(encoding="utf-8")

    # Any of these substrings signals a valid operational note
    has_note = (
        "Nota operativa" in content
        or "ADDON" in content
        or "decisiones del personal" in content
        or "decisiones operacionales" in content
    )
    assert has_note, (
        "glossary.md must contain an operational footnote explaining that duration "
        "deltas in color/treatment/highlights are ADDON (operator-decided), not "
        "customer-facing variant choices."
    )


# ---------------------------------------------------------------------------
# REQ-TE-5 / T2.2 — critical_rules.md contains R-34
# ---------------------------------------------------------------------------


def test_critical_rules_r34_rule_number_present() -> None:
    """T2.2 [RED→GREEN]: R-34 must be present in critical_rules.md.

    RED until T2.4 appends R-34.
    """
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")

    assert "[R34]" in content, (
        "critical_rules.md must contain [R34] after T2.4. "
        "This is the new rule prohibiting duration-variant presentation to customers."
    )


def test_critical_rules_r34_canonical_phrase() -> None:
    """T2.2 companion: canonical substring from design ADR-DR-2 must be present.

    The exact phrase is the golden-test anchor — if it changes, the golden test
    must be updated to reflect the new canonical wording.
    """
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")

    canonical = (
        "NUNCA presentes al cliente una variante cuyo único distintivo sea un delta de duración"
    )
    assert canonical in content, (
        f"critical_rules.md must contain the canonical R-34 phrase:\n  {canonical}\n"
        "This phrase is the spec-mandated anchor string (REQ-PR-2)."
    )


def test_critical_rules_r34_names_affected_services() -> None:
    """T2.2 companion: R-34 must explicitly name at least one reclassified service."""
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")

    assert "Tinte Extra" in content, (
        "R-34 must name 'Tinte Extra' as an example of a duration-delta service. "
        "This satisfies REQ-PR-2's requirement to name affected services explicitly."
    )


# ---------------------------------------------------------------------------
# REQ-TE-2 / T2.1 papercut-fixes — R-35 round-trip rule
# ---------------------------------------------------------------------------


def test_critical_rules_r35_rule_present() -> None:
    """T2.1 [RED→GREEN]: R-35 must be present in critical_rules.md.

    RED until T2.2 appends R-35.
    """
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")

    assert "[R35]" in content, (
        "critical_rules.md must contain [R35] after T2.2. "
        "R-35 documents the partial_resolved_ids → pre_resolved_service_ids round-trip contract."
    )


def test_critical_rules_r35_canonical_substrings() -> None:
    """T2.1 companion: both canonical substrings from design ADR-DR-3 must be present.

    The golden-test anchor ensures the round-trip contract names both
    the field returned by the tool and the argument the LLM must re-pass.
    RED until T2.2 appends R-35.
    """
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")

    assert "partial_resolved_ids" in content, (
        "R-35 must reference 'partial_resolved_ids' — the field returned by update_booking "
        "when status='ambiguous' with already-resolved services."
    )
    assert "pre_resolved_service_ids" in content, (
        "R-35 must reference 'pre_resolved_service_ids' — the argument the LLM must "
        "re-pass on the next update_booking call to avoid re-resolving known services."
    )
