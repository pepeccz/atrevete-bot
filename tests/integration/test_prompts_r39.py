"""T17 — I3: Integration test asserting R-39 is present in critical_rules.md and examples.md.

Spec: REQ-I3 / SC-I3-A through SC-I3-F

TDD: Written before T18/T19 add the actual content. These tests will fail (RED)
until T18 appends R-39 to critical_rules.md and T19 appends Ejemplo 7 to examples.md.

These are file-level golden tests (no DB or network needed).
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
CRITICAL_RULES_PATH = PROJECT_ROOT / "agent" / "prompts" / "shared" / "critical_rules.md"
EXAMPLES_PATH = PROJECT_ROOT / "agent" / "prompts" / "shared" / "examples.md"


def test_critical_rules_file_exists() -> None:
    assert CRITICAL_RULES_PATH.exists(), f"critical_rules.md not found at {CRITICAL_RULES_PATH}"


def test_examples_file_exists() -> None:
    assert EXAMPLES_PATH.exists(), f"examples.md not found at {EXAMPLES_PATH}"


def test_r39_rule_present() -> None:
    """SC-I3-A/B/C/D: [R-39] marker must be present in critical_rules.md."""
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")
    assert "[R-39]" in content, (
        "critical_rules.md does not contain '[R-39]'. "
        "Apply T18 to add the clarification gate rule."
    )


def test_r39_contains_no_procesable() -> None:
    """R-39 rule must describe 'no procesable' (non-processable) input handling."""
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")
    assert "[R-39]" in content
    # Find the R-39 line and verify it contains the key concept
    lines = content.splitlines()
    r39_lines = [line for line in lines if "[R-39]" in line]
    assert r39_lines, "R-39 not found as a line in critical_rules.md"
    r39_text = " ".join(r39_lines).lower()
    assert (
        "no procesable" in r39_text or "procesable" in r39_text
    ), f"R-39 line does not contain 'procesable': {r39_lines}"


def test_r39_requires_open_question() -> None:
    """R-39 must require asking an open question (pregunta abierta) before acting."""
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")
    # Get full R-39 block (may span multiple lines — find from [R-39] to next [R- or end)
    start = content.find("[R-39]")
    assert start >= 0, "R-39 not found"
    # Find the next rule marker after R-39
    next_rule = content.find("[R-", start + 1)
    r39_block = content[start:next_rule] if next_rule > 0 else content[start:]
    assert "pregunta" in r39_block.lower() and "abierta" in r39_block.lower(), (
        f"R-39 block does not mention 'pregunta abierta' (open question requirement): "
        f"{r39_block[:300]}"
    )


def test_ejemplo_7_present() -> None:
    """SC-I3-B/D: examples.md must contain 'Ejemplo 7'."""
    content = EXAMPLES_PATH.read_text(encoding="utf-8")
    assert "Ejemplo 7" in content, (
        "examples.md does not contain 'Ejemplo 7'. "
        "Apply T19 to add the emoji-only input example."
    )


def test_ejemplo_7_references_r39() -> None:
    """Ejemplo 7 in examples.md must reference [→R-39] or R-39."""
    content = EXAMPLES_PATH.read_text(encoding="utf-8")
    assert "Ejemplo 7" in content, "Ejemplo 7 not found in examples.md"

    start = content.find("Ejemplo 7")
    # Find end of Ejemplo 7 block (next heading or end of file)
    next_heading = content.find("### Ejemplo", start + 1)
    block = content[start:next_heading] if next_heading > 0 else content[start:]

    assert "R-39" in block, f"Ejemplo 7 block does not reference R-39: {block[:300]}"


# ---------------------------------------------------------------------------
# Change L (L1) — R-39 must demand a PURE open question (no category priming)
# ---------------------------------------------------------------------------


def _get_r39_block() -> str:
    """Return the full R-39 block from critical_rules.md."""
    content = CRITICAL_RULES_PATH.read_text(encoding="utf-8")
    start = content.find("[R-39]")
    assert start >= 0, "R-39 not found in critical_rules.md"
    next_rule = content.find("[R-", start + 1)
    return content[start:next_rule] if next_rule > 0 else content[start:]


def test_r39_forbids_category_enumeration() -> None:
    """L1: R-39 must explicitly forbid enumerating categories/services in the reply."""
    block = _get_r39_block().lower()
    assert "enumerar" in block or "enumeres" in block, (
        "R-39 must explicitly forbid enumerating categories in the clarification "
        f"reply (expected 'enumerar'/'enumeres' in block): {block[:400]}"
    )


def test_r39_no_longer_contains_category_enumeration_example() -> None:
    """L1 (negative): the old category-enumeration example must be gone from R-39.

    The pre-Change-L rule primed the customer with '¿Buscas corte, peinado,
    color u otro servicio?'. The clarification reply must now be a pure open
    question — no category list anywhere in the R-39 block.
    """
    block = _get_r39_block().lower()
    for enumeration in ("corte, peinado, color", "corte, color, depilación"):
        assert enumeration not in block, (
            f"R-39 still contains the category-enumeration example {enumeration!r}. "
            "Change L requires a pure open question with no category priming."
        )


def test_r39_contains_pure_open_question_example() -> None:
    """L1: R-39 must show the pure open question as the correct reply."""
    block = _get_r39_block()
    assert "¿En qué puedo ayudarte?" in block, (
        "R-39 must include the pure open question example '¿En qué puedo ayudarte?': "
        f"{block[:400]}"
    )


def test_ejemplo_7_good_reply_does_not_enumerate_categories() -> None:
    """L1: the <good> reply in examples.md Ejemplo 7 must be a pure open question."""
    content = EXAMPLES_PATH.read_text(encoding="utf-8")
    start = content.find("Ejemplo 7")
    assert start >= 0, "Ejemplo 7 not found in examples.md"
    next_heading = content.find("### Ejemplo", start + 1)
    block = content[start:next_heading] if next_heading > 0 else content[start:]

    good_lines = [line for line in block.splitlines() if "<good>" in line]
    assert good_lines, f"Ejemplo 7 has no <good> line: {block[:300]}"
    for line in good_lines:
        lowered = line.lower()
        for enumeration in ("corte, peinado, color", "corte, color, depilación"):
            assert (
                enumeration not in lowered
            ), f"Ejemplo 7 <good> reply still enumerates categories: {line!r}"
