"""T9 — Prompt content tests.

Verifies that prompt files contain the required rules (spec R6.1–R6.5).
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROMPTS_DIR = Path(__file__).parent.parent.parent / "agent" / "prompts" / "shared"


def _read(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T9.1 — critical_rules.md must contain today weekday rule
# ---------------------------------------------------------------------------


def test_critical_rules_contains_today_weekday_rule():
    """critical_rules.md must instruct LLM to read weekday from <today> (R4.3)."""
    content = _read("critical_rules.md")
    assert "dia_semana" in content, (
        "critical_rules.md must reference dia_semana from <today>"
    )
    # Must say something about not inventing / must read from today
    lower = content.lower()
    has_rule = (
        "dia_semana" in lower
        and ("today" in lower or "<today>" in lower or "hoy" in lower)
    )
    assert has_rule, (
        "critical_rules.md must contain a rule linking dia_semana to <today>"
    )


# ---------------------------------------------------------------------------
# T9.2 — critical_rules.md must contain no-hallucinated-slots rule
# ---------------------------------------------------------------------------


def test_critical_rules_contains_no_hallucinated_slots_rule():
    """critical_rules.md must prohibit invented slots (R6.2b)."""
    content = _read("critical_rules.md")
    lower = content.lower()
    # Must mention availability block and prohibit invention
    has_availability_ref = "<availability>" in content or "availability" in lower
    has_no_invent = (
        "no inventes" in lower
        or "nunca inventes" in lower
        or "must come from" in lower
        or "solo de" in lower
        or "solo huecos" in lower
        or "huecos.*disponibilidad" in lower
        or "no debe inventar" in lower
    )
    assert has_availability_ref, "critical_rules.md must reference <availability> block"
    assert has_no_invent, "critical_rules.md must prohibit inventing slots"


# ---------------------------------------------------------------------------
# T9.3 — booking_flow.md must describe <availability> as primary source
# ---------------------------------------------------------------------------


def test_booking_flow_describes_availability_as_primary():
    """booking_flow.md must describe <availability> as primary slot source (R6.1)."""
    content = _read("booking_flow.md")
    lower = content.lower()
    has_availability = "<availability>" in content or "bloque availability" in lower
    assert has_availability, (
        "booking_flow.md must describe the <availability> block"
    )


# ---------------------------------------------------------------------------
# T9.4 — tools_contract.md must describe pre-book gate
# ---------------------------------------------------------------------------


def test_tools_contract_describes_prebook_gate():
    """tools_contract.md must describe pre_book_validation_required gate (R6.3)."""
    content = _read("tools_contract.md")
    lower = content.lower()
    has_gate = (
        "pre_book_validation" in lower
        or "pre_book_validated" in lower
        or "slot_time" in lower
        or "revalidar" in lower
        or "revalidación" in lower
    )
    assert has_gate, (
        "tools_contract.md must describe the pre-book re-validation gate"
    )


# ---------------------------------------------------------------------------
# T9.5 — No rule duplicated across prompt files
# ---------------------------------------------------------------------------


def test_no_rule_duplicated_across_prompt_files():
    """No substantial paragraph must appear verbatim in more than one prompt file (R6.4)."""
    files = ["critical_rules.md", "booking_flow.md", "tools_contract.md"]
    contents = {name: _read(name) for name in files}

    # Extract non-trivial paragraphs (> 60 chars) from each file
    def extract_paragraphs(text: str) -> list[str]:
        return [
            p.strip()
            for p in text.split("\n\n")
            if len(p.strip()) > 60 and not p.strip().startswith("#")
        ]

    paragraphs_by_file = {name: extract_paragraphs(c) for name, c in contents.items()}

    duplicates = []
    file_names = list(paragraphs_by_file.keys())
    for i, name_a in enumerate(file_names):
        for name_b in file_names[i + 1:]:
            for para_a in paragraphs_by_file[name_a]:
                for para_b in paragraphs_by_file[name_b]:
                    # Check if either paragraph is fully contained in the other
                    if para_a in para_b or para_b in para_a:
                        duplicates.append((name_a, name_b, para_a[:80]))

    assert duplicates == [], (
        f"Duplicate paragraphs found across prompt files:\n"
        + "\n".join(f"  {a} ↔ {b}: {snip!r}" for a, b, snip in duplicates[:3])
    )
