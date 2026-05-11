"""Scenario G / R4.4 — 7-step canonical order assertion (HARD FAIL).

Tests that booking_flow.md encodes the canonical 7-step booking flow in the
correct sequence. Asserts:
  - All 8 Paso headers are present: Paso 1, 2, 2.5, 3, 4, 5, 6, 7.
  - The headers appear in the correct order in the file.
  - Paso 2 (disambiguation) comes before Paso 5 (slots).
  - Paso 5 (slots) comes before Paso 6 (nombre).
  - Paso 3 (confirmación) comes before Paso 5 (slots).
  - Paso 6 region contains "Primer Apellido" (one surname rule).

This is a HARD FAIL test — no xfail. It validates the structural invariant
introduced by PR-3 Task 3.1 (booking_flow.md 7-step rewrite).

Refs: spec R3.1, R3.6, R4.4, Scenario G, tasks 4.8, design §2 Slice 4
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BOOKING_FLOW_PATH = (
    Path(__file__).parent.parent.parent.parent  # project root
    / "agent"
    / "prompts"
    / "shared"
    / "booking_flow.md"
)

# Expected Paso headers in canonical order (design §2 Slice 3, spec R3.1)
EXPECTED_PASO_SEQUENCE = [
    "Paso 1",
    "Paso 2",
    "Paso 2.5",
    "Paso 3",
    "Paso 4",
    "Paso 5",
    "Paso 6",
    "Paso 7",
]

# Pattern to find Paso headers (bold or plain header style)
PASO_HEADER_PATTERN = re.compile(
    r"\*\*Paso\s+([\d.]+)\s*[—–-]",  # **Paso N — ...** form
    re.MULTILINE,
)


def _load_booking_flow() -> str:
    """Load booking_flow.md content. Fail test if file not found."""
    if not BOOKING_FLOW_PATH.exists():
        pytest.fail(
            f"booking_flow.md not found at {BOOKING_FLOW_PATH}. "
            "Verify PR-3 is merged and the file path is correct."
        )
    return BOOKING_FLOW_PATH.read_text(encoding="utf-8")


def _extract_paso_headers(content: str) -> list[tuple[str, int]]:
    """Return list of (paso_label, char_position) for all Paso headers found in order."""
    headers: list[tuple[str, int]] = []
    for m in PASO_HEADER_PATTERN.finditer(content):
        label = f"Paso {m.group(1)}"
        headers.append((label, m.start()))
    return headers


# ---------------------------------------------------------------------------
# HARD FAIL assertions
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_all_paso_headers_present():
    """HARD FAIL: all 8 Paso headers (1, 2, 2.5, 3, 4, 5, 6, 7) must be present."""
    content = _load_booking_flow()
    headers = _extract_paso_headers(content)
    found_labels = [label for label, _ in headers]

    for expected in EXPECTED_PASO_SEQUENCE:
        assert expected in found_labels, (
            f"Expected '{expected}' header not found in booking_flow.md. "
            f"Found headers: {found_labels}. "
            "Verify PR-3 Task 3.1 added all 8 Paso headers."
        )


@pytest.mark.integration
def test_paso_headers_in_canonical_order():
    """HARD FAIL: Paso headers must appear in file in canonical sequence order."""
    content = _load_booking_flow()
    headers = _extract_paso_headers(content)
    found_labels = [label for label, _ in headers]

    # Filter to only the expected labels (ignore any extra headers)
    filtered = [lbl for lbl in found_labels if lbl in EXPECTED_PASO_SEQUENCE]

    assert filtered == EXPECTED_PASO_SEQUENCE, (
        f"Paso headers are not in canonical order.\n"
        f"Expected: {EXPECTED_PASO_SEQUENCE}\n"
        f"Found:    {filtered}\n"
        "Verify PR-3 Task 3.1 preserved the 7-step canonical ordering."
    )


@pytest.mark.integration
def test_paso2_before_paso5():
    """HARD FAIL: Paso 2 (disambiguation) must appear before Paso 5 (slots) in file."""
    content = _load_booking_flow()
    headers = _extract_paso_headers(content)
    pos_by_label = dict(headers)

    assert "Paso 2" in pos_by_label, "Paso 2 not found in booking_flow.md"
    assert "Paso 5" in pos_by_label, "Paso 5 not found in booking_flow.md"

    assert pos_by_label["Paso 2"] < pos_by_label["Paso 5"], (
        f"Paso 2 (char {pos_by_label['Paso 2']}) must come BEFORE "
        f"Paso 5 (char {pos_by_label['Paso 5']}). "
        "Disambiguation must precede slot offering (spec R4.4)."
    )


@pytest.mark.integration
def test_paso5_before_paso6():
    """HARD FAIL: Paso 5 (slots) must appear before Paso 6 (nombre) in file."""
    content = _load_booking_flow()
    headers = _extract_paso_headers(content)
    pos_by_label = dict(headers)

    assert "Paso 5" in pos_by_label, "Paso 5 not found in booking_flow.md"
    assert "Paso 6" in pos_by_label, "Paso 6 not found in booking_flow.md"

    assert pos_by_label["Paso 5"] < pos_by_label["Paso 6"], (
        f"Paso 5 (char {pos_by_label['Paso 5']}) must come BEFORE "
        f"Paso 6 (char {pos_by_label['Paso 6']}). "
        "Slot offering must precede name collection."
    )


@pytest.mark.integration
def test_paso3_before_paso5():
    """HARD FAIL: Paso 3 (confirmación) must appear before Paso 5 (slots) in file."""
    content = _load_booking_flow()
    headers = _extract_paso_headers(content)
    pos_by_label = dict(headers)

    assert "Paso 3" in pos_by_label, "Paso 3 not found in booking_flow.md"
    assert "Paso 5" in pos_by_label, "Paso 5 not found in booking_flow.md"

    assert pos_by_label["Paso 3"] < pos_by_label["Paso 5"], (
        f"Paso 3 (char {pos_by_label['Paso 3']}) must come BEFORE "
        f"Paso 5 (char {pos_by_label['Paso 5']}). "
        "Confirmation/upsell must not occur after slots are offered (spec R4.4)."
    )


@pytest.mark.integration
def test_paso6_contains_primer_apellido():
    """HARD FAIL: Paso 6 region must contain 'Primer Apellido' (one-surname rule, spec R3.6)."""
    content = _load_booking_flow()
    headers = _extract_paso_headers(content)
    pos_by_label = dict(headers)

    assert "Paso 6" in pos_by_label, "Paso 6 not found in booking_flow.md"

    paso6_start = pos_by_label["Paso 6"]
    # Paso 6 text extends to Paso 7 (or end of file)
    paso7_start = pos_by_label.get("Paso 7", len(content))
    paso6_text = content[paso6_start:paso7_start]

    has_primer_apellido = "Primer Apellido" in paso6_text or "primer apellido" in paso6_text
    assert has_primer_apellido, (
        f"Paso 6 must contain 'Primer Apellido' instruction (one-surname rule). "
        f"Paso 6 text:\n{paso6_text}\n"
        "Verify PR-3 Task 3.1 added 'un solo apellido, no dos' to Paso 6."
    )


@pytest.mark.integration
def test_no_paso0_present():
    """HARD FAIL: 'Paso 0' must not appear in booking_flow.md (was dropped in PR-3)."""
    content = _load_booking_flow()

    has_paso0 = bool(re.search(r"Paso\s+0", content))
    assert not has_paso0, (
        "Found 'Paso 0' in booking_flow.md — it must be absent. "
        "PR-3 Task 3.1 dropped Paso 0 as redundant with R9/R9b."
    )


@pytest.mark.integration
def test_paso5_references_gap_explanation():
    """HARD FAIL: Paso 5 region must reference gap_explanation_hint (design integration)."""
    content = _load_booking_flow()
    headers = _extract_paso_headers(content)
    pos_by_label = dict(headers)

    assert "Paso 5" in pos_by_label, "Paso 5 not found in booking_flow.md"
    assert "Paso 6" in pos_by_label, "Paso 6 not found in booking_flow.md"

    paso5_start = pos_by_label["Paso 5"]
    paso6_start = pos_by_label["Paso 6"]
    paso5_text = content[paso5_start:paso6_start]

    assert "gap_explanation_hint" in paso5_text, (
        f"Paso 5 must reference 'gap_explanation_hint' (R30 integration). "
        f"Paso 5 text:\n{paso5_text}\n"
        "Verify PR-3 Task 3.1 added gap_explanation_hint reference to Paso 5."
    )
