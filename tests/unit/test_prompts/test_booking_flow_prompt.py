"""T7.a RED — booking_flow.md line-count + no numbered steps.

R-IDs: R11
"""
from __future__ import annotations

import re
from pathlib import Path

BOOKING_FLOW_PATH = (
    Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "shared" / "booking_flow.md"
)


def _content_lines(text: str) -> list[str]:
    """Non-blank, non-comment lines."""
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_line_count() -> None:
    text = BOOKING_FLOW_PATH.read_text(encoding="utf-8")
    lines = _content_lines(text)
    # Budget raised to accommodate Paso 0 and Paso 1 blocks (SDD change
    # prompt-audience-regression-fix-generic). Previous budget was 10.
    # Budget raised again for Paso 1.5, Paso 4, Paso 4b, updated confirmation
    # template (SDD change booking-flow-name-notes-extras-loop). Previous was 60.
    assert len(lines) <= 75, (
        f"booking_flow.md has {len(lines)} content lines; expected ≤60.\n"
        f"Content lines:\n" + "\n".join(f"  {l}" for l in lines)
    )


def test_no_numbered_steps() -> None:
    text = BOOKING_FLOW_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        assert not re.match(r"^\s*\d+\.", line), (
            f"Found numbered step: {line!r}"
        )
        # "Step" (English) is still forbidden; "Paso" is now allowed (Paso 0/Paso 1 sections added).
        assert "Step" not in line, f"Found 'Step' in line: {line!r}"


def test_next_step_contract_present() -> None:
    text = BOOKING_FLOW_PATH.read_text(encoding="utf-8")
    assert "next_step" in text, "booking_flow.md must mention 'next_step'"


def test_update_booking_mentioned() -> None:
    text = BOOKING_FLOW_PATH.read_text(encoding="utf-8")
    assert "update_booking" in text, "booking_flow.md must mention 'update_booking'"
