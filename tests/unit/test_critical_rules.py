"""Tests for R-40 and R-41 in critical_rules.md.

Change J: hallucination-tolerant-architecture-bundle.
REQ-J6, REQ-J7.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CRITICAL_RULES_PATH = (
    Path(__file__).parent.parent.parent / "agent" / "prompts" / "shared" / "critical_rules.md"
)


@pytest.fixture(scope="module")
def rules_text() -> str:
    return CRITICAL_RULES_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# R-40 — No numeric price quoting
# ---------------------------------------------------------------------------


def test_r40_entry_exists(rules_text: str) -> None:
    """R-40 must be present with its numbered identifier."""
    assert "[R-40]" in rules_text, "R-40 entry missing from critical_rules.md"


def test_r40_prohibits_numeric_prices(rules_text: str) -> None:
    """R-40 must include prohibition language about numeric prices."""
    r40_start = rules_text.find("[R-40]")
    assert r40_start != -1, "R-40 entry missing"
    # Find end of R-40 block (next rule or end of file)
    r41_start = rules_text.find("[R-41]", r40_start)
    r40_block = rules_text[r40_start:r41_start] if r41_start != -1 else rules_text[r40_start:]
    # Must mention price prohibition
    assert (
        "precio" in r40_block.lower() or "price" in r40_block.lower()
    ), "R-40 must mention price/precio prohibition"
    # Must mention NUNCA or NEVER
    assert (
        "nunca" in r40_block.lower() or "never" in r40_block.lower()
    ), "R-40 must include NUNCA/NEVER prohibition"


def test_r40_has_example(rules_text: str) -> None:
    """R-40 must include at least one correct/incorrect example."""
    r40_start = rules_text.find("[R-40]")
    assert r40_start != -1, "R-40 entry missing"
    r41_start = rules_text.find("[R-41]", r40_start)
    r40_block = rules_text[r40_start:r41_start] if r41_start != -1 else rules_text[r40_start:]
    # Must include MAL/BIEN example pair OR explicit example markers
    has_example = (
        ("MAL:" in r40_block or "mal:" in r40_block.lower())
        and ("BIEN:" in r40_block or "bien:" in r40_block.lower())
    ) or "ejemplo" in r40_block.lower()
    assert has_example, "R-40 must include a MAL:/BIEN: example pair"


def test_r40_references_price_field_precondition(rules_text: str) -> None:
    """R-40 must mention that price quoting is prohibited until catalog exposes price field."""
    r40_start = rules_text.find("[R-40]")
    assert r40_start != -1, "R-40 entry missing"
    r41_start = rules_text.find("[R-41]", r40_start)
    r40_block = rules_text[r40_start:r41_start] if r41_start != -1 else rules_text[r40_start:]
    # Must reference price field condition
    assert (
        "price" in r40_block or "precio" in r40_block.lower()
    ), "R-40 must reference the price field precondition"


# ---------------------------------------------------------------------------
# R-41 — No preference inference without grounded data
# ---------------------------------------------------------------------------


def test_r41_entry_exists(rules_text: str) -> None:
    """R-41 must be present with its numbered identifier."""
    assert "[R-41]" in rules_text, "R-41 entry missing from critical_rules.md"


def test_r41_prohibits_preference_inference(rules_text: str) -> None:
    """R-41 must prohibit inferring preferences when memory/history slots are empty."""
    r41_start = rules_text.find("[R-41]")
    assert r41_start != -1, "R-41 entry missing"
    # Find end of R-41 block (next rule or end of file)
    next_rule = rules_text.find("[R-", r41_start + 5)
    r41_block = rules_text[r41_start:next_rule] if next_rule != -1 else rules_text[r41_start:]
    # Must mention inference/preferencia prohibition
    assert (
        "preferen" in r41_block.lower() or "inferir" in r41_block.lower()
    ), "R-41 must mention preference inference prohibition"
    # Must mention NUNCA
    assert (
        "nunca" in r41_block.lower() or "never" in r41_block.lower()
    ), "R-41 must include NUNCA prohibition"


def test_r41_references_empty_slots(rules_text: str) -> None:
    """R-41 must reference customer_memories or past_appointments slots being empty."""
    r41_start = rules_text.find("[R-41]")
    assert r41_start != -1, "R-41 entry missing"
    next_rule = rules_text.find("[R-", r41_start + 5)
    r41_block = rules_text[r41_start:next_rule] if next_rule != -1 else rules_text[r41_start:]
    has_memory_ref = "customer_memories" in r41_block or "past_appointments" in r41_block
    assert has_memory_ref, "R-41 must reference <customer_memories> or <past_appointments> slots"


def test_r41_has_example(rules_text: str) -> None:
    """R-41 must include at least one correct/incorrect example."""
    r41_start = rules_text.find("[R-41]")
    assert r41_start != -1, "R-41 entry missing"
    next_rule = rules_text.find("[R-", r41_start + 5)
    r41_block = rules_text[r41_start:next_rule] if next_rule != -1 else rules_text[r41_start:]
    has_example = (
        ("MAL:" in r41_block or "mal:" in r41_block.lower())
        and ("BIEN:" in r41_block or "bien:" in r41_block.lower())
    ) or "ejemplo" in r41_block.lower()
    assert has_example, "R-41 must include a MAL:/BIEN: example pair"


# ---------------------------------------------------------------------------
# R-39 — Clarification gate must use a PURE open question (Change L / L1)
# ---------------------------------------------------------------------------


def _r39_block(rules_text: str) -> str:
    start = rules_text.find("[R-39]")
    assert start != -1, "R-39 entry missing from critical_rules.md"
    next_rule = rules_text.find("[R-", start + 1)
    return rules_text[start:next_rule] if next_rule != -1 else rules_text[start:]


def test_r39_entry_exists(rules_text: str) -> None:
    """R-39 must be present with its numbered identifier."""
    assert "[R-39]" in rules_text, "R-39 entry missing from critical_rules.md"


def test_r39_forbids_enumeration(rules_text: str) -> None:
    """L1: R-39 must forbid enumerating categories/services in the clarification reply."""
    block = _r39_block(rules_text).lower()
    assert (
        "enumerar" in block or "enumeres" in block
    ), "R-39 must forbid category enumeration in the clarification reply"
    assert (
        "nunca" in block or "prohibido" in block
    ), "R-39 must phrase the enumeration ban as a hard prohibition (NUNCA/PROHIBIDO)"


def test_r39_does_not_contain_enumeration_example(rules_text: str) -> None:
    """L1 (negative): the old category-enumeration example must be gone."""
    block = _r39_block(rules_text).lower()
    assert "corte, peinado, color" not in block, (
        "R-39 still contains the old category-enumeration example "
        "('corte, peinado, color...') — the clarification reply must be a pure open question"
    )


def test_r39_keeps_open_question_requirement(rules_text: str) -> None:
    """L1: R-39 must still demand a short open question before any action."""
    block = _r39_block(rules_text).lower()
    assert "pregunta abierta" in block, "R-39 must require a 'pregunta abierta'"


def test_r41_applies_when_both_slots_empty(rules_text: str) -> None:
    """R-41 must explicitly cover both memory slots being empty."""
    r41_start = rules_text.find("[R-41]")
    assert r41_start != -1, "R-41 entry missing"
    next_rule = rules_text.find("[R-", r41_start + 5)
    r41_block = rules_text[r41_start:next_rule] if next_rule != -1 else rules_text[r41_start:]
    # Both slots must be mentioned
    has_both = "customer_memories" in r41_block and "past_appointments" in r41_block
    assert has_both, "R-41 must reference both <customer_memories> and <past_appointments>"
