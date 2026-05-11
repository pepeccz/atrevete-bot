"""T3.1 / T3.3 / T3.5 [RED] — Disambiguation resilience prompt rules golden tests.

Asserts that:
  - R-32 (anti-audience-hallucination) is present in critical_rules.md with
    canonical substring "NUNCA infieras `audience`"
  - R-33 (no auto-disclosure by LLM) is present in critical_rules.md with
    canonical substring "__DISCLOSURE__"
  - R9b is amended with the principal-accept clause containing "variant_resolved=true"
  - glossary.md has the "Mapeo de ejes de desambiguación" section with axis table

These are HARD FAIL golden tests. No xfail.

Refs: REQ-PR-1, REQ-PR-2, REQ-PR-3, REQ-PR-4 (spec #5275); design #5277 §Prompt rule wording.
Tasks: T3.1 (RED), T3.3 (RED), T3.5 (RED).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SHARED = Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "shared"


def _read(filename: str) -> str:
    path = _SHARED / filename
    if not path.exists():
        pytest.fail(f"{filename} not found at {path}. Verify prompt files exist.")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T3.1 [RED] — R-32 anti-audience-hallucination
# ---------------------------------------------------------------------------


def test_r32_anti_audience_hallucination_present():
    """R-32 canonical substring must be present in critical_rules.md.

    Canonical: "NUNCA infieras `audience`"
    Refs: REQ-PR-1, spec A2, design I-2 (R-32 numbering, not R-25).
    """
    content = _read("critical_rules.md")
    assert "NUNCA infieras `audience`" in content, (
        "R-32 anti-audience-hallucination rule not found in critical_rules.md. "
        "Expected canonical substring: 'NUNCA infieras `audience`'. "
        "T3.2 must add R-32 to the file."
    )


def test_r32_references_catalog_token_inference():
    """R-32 must explain that audience MUST NOT come from service name tokens."""
    content = _read("critical_rules.md")
    # The rule must mention that the catalog name tokens are not valid audience sources
    assert "nombre del servicio" in content or "tokens" in content, (
        "R-32 must explain that audience cannot be inferred from service name tokens. "
        "Verify the rule body references catalog token inference."
    )


def test_r32_mentions_explicit_customer_signal():
    """R-32 must state valid audience sources: explicit customer signal OR customer record."""
    content = _read("critical_rules.md")
    # Valid audience sources: explicit customer signal or <customer> block
    assert "explícita" in content or "explicitamente" in content.lower(), (
        "R-32 must state that audience requires an explicit customer signal. "
        "Verify rule body references explicit customer declaration."
    )


# ---------------------------------------------------------------------------
# T3.3 [RED] — R-33 no auto-disclosure
# ---------------------------------------------------------------------------


def test_r33_no_autodisclosure_canonical_substring():
    """R-33 canonical substring __DISCLOSURE__ must be present in critical_rules.md.

    Canonical: "__DISCLOSURE__"
    Refs: REQ-PR-2, spec A3, design §R-33 wording.
    """
    content = _read("critical_rules.md")
    assert "__DISCLOSURE__" in content, (
        "R-33 no-auto-disclosure rule not found in critical_rules.md. "
        "Expected canonical substring: '__DISCLOSURE__'. "
        "T3.4 must add R-33 to the file."
    )


def test_r33_references_middleware():
    """R-33 must state middleware owns the disclosure text (not the LLM)."""
    content = _read("critical_rules.md")
    assert "middleware" in content.lower(), (
        "R-33 must reference 'middleware' as the owner of the disclosure text. "
        "Verify rule body mentions that middleware inserts the AI disclosure."
    )


def test_r33_reinforces_r8():
    """R-33 must reference R8 (existing disclosure rule) to avoid contradiction."""
    content = _read("critical_rules.md")
    assert "R8" in content, (
        "R-33 must reference R8 to reinforce the existing disclosure rule. "
        "Verify rule body contains 'R8'."
    )


# ---------------------------------------------------------------------------
# T3.5 [RED] — Glossary axis-mapping section + R9b amendment
# ---------------------------------------------------------------------------


def test_glossary_has_axis_mapping_section():
    """glossary.md must contain the 'Ejes de Desambiguación' section.

    Title per spec REQ-PR-3 and design: "Ejes de Desambiguación".
    Refs: REQ-PR-3, design §Glossary axis-mapping section.
    """
    content = _read("glossary.md")
    assert "Ejes de Desambiguación" in content, (
        "glossary.md missing 'Ejes de Desambiguación' section. "
        "T3.6 must add the axis-mapping table to the file with the correct title."
    )


def test_glossary_axis_mapping_has_four_columns():
    """Axis-mapping table must use 4 columns per design: axis, trigger, question, family example.

    Asserts that the table header contains all four column names.
    Refs: REQ-PR-3, design §Glossary axis-mapping 4-column structure (W2 fix).
    """
    content = _read("glossary.md")
    assert "Trigger condition" in content, (
        "Axis-mapping table must have a 'Trigger condition' column. "
        "Design specifies a 4-column table: axis, trigger, question, example family."
    )
    assert "Ejemplo de familia de servicios" in content, (
        "Axis-mapping table must have an 'Ejemplo de familia de servicios' column. "
        "Design specifies a 4-column table with concrete service family examples."
    )


def test_glossary_axis_mapping_has_audience_axis():
    """Axis-mapping section must contain the audience axis row."""
    content = _read("glossary.md")
    assert "audience_required" in content, (
        "Axis-mapping table must include the 'audience_required' trigger. "
        "Verify the audience axis row is present."
    )


def test_glossary_axis_mapping_has_variant_axis():
    """Axis-mapping section must contain at least one variant axis row."""
    content = _read("glossary.md")
    assert "variant_required" in content, (
        "Axis-mapping table must include the 'variant_required' trigger. "
        "Verify the variant axis row is present."
    )


def test_glossary_axis_mapping_mentions_candidates():
    """Axis-mapping table must reference payload.candidates or {candidates}."""
    content = _read("glossary.md")
    assert "candidates" in content, (
        "Axis-mapping table must reference candidates (from disambiguation payload). "
        "Verify axis rows mention {candidates} or payload.candidates."
    )


def test_r9b_principal_accept_clause_present():
    """R9b must contain the principal-accept clause with variant_resolved=true.

    Canonical substring: "variant_resolved=true"
    Refs: REQ-PR-4, design §R9b amendment.
    """
    content = _read("critical_rules.md")
    assert "variant_resolved=true" in content, (
        "R9b principal-accept clause not found in critical_rules.md. "
        "Expected substring: 'variant_resolved=true'. "
        "T3.6 must amend R9b to add the principal-accept clause."
    )


def test_r9b_keeps_existing_exceptions():
    """R9b must still contain the original exception clauses (a) and (b)."""
    content = _read("critical_rules.md")
    # Original R9b had exceptions (a) and (b)
    assert "(a)" in content and "(b)" in content, (
        "R9b must preserve original exception clauses (a) and (b). "
        "The amendment must APPEND, not replace, the existing clause text."
    )
