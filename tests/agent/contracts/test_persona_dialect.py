"""Static dialect tests: voseo markers must be absent from booking persona files.

R4 — Rioplatense voseo is prohibited. Castellano peninsular tuteo is required.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Files to check
_PROMPT_BUILDER = Path(__file__).parents[3] / "agent" / "booking" / "prompt_builder.py"
_ACTIONS = Path(__file__).parents[3] / "agent" / "booking" / "actions.py"

# Prohibited voseo patterns (case-insensitive where appropriate)
_VOSEO_PATTERNS = [
    r"\bsos\b",
    r"\bRespondés\b",
    r"\belegí\b",
    r"\banotá\b",
    r"\bidentificá\b",
    r"\bextraé\b",
    r"\bquerés\b",
    r"\bdecime\b",
    r"rioplatense",
    # Additional voseo imperatives present in the current code
    r"\bUsá\b",
    r"\busá\b",
    r"\bConvertí\b",
    r"\bConsultá\b",
    r"\bMostrá\b",
    r"\bPedí\b",
    r"\bpedí\b",
    r"\bPreguntá\b",
    r"\bpreguntá\b",
    r"\bmarcá\b",
    r"\bIdentificá\b",
    r"\bExtraé\b",
]


def _find_voseo_matches(filepath: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_no, pattern, matched_text) for all voseo matches."""
    matches = []
    text = filepath.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in _VOSEO_PATTERNS:
            if re.search(pattern, line):
                matches.append((lineno, pattern, line.strip()))
    return matches


def test_no_voseo_in_prompt_builder():
    """prompt_builder.py must contain zero voseo markers.

    RED: fails because the current persona block uses voseo ('Sos Maite',
    'Respondés', 'rioplatense') and step instructions use voseo imperatives.
    """
    assert _PROMPT_BUILDER.exists(), f"File not found: {_PROMPT_BUILDER}"
    matches = _find_voseo_matches(_PROMPT_BUILDER)
    if matches:
        details = "\n".join(
            f"  Line {lineno}: pattern={pattern!r}  →  {text}" for lineno, pattern, text in matches
        )
        pytest.fail(
            f"Voseo markers found in {_PROMPT_BUILDER.name} ({len(matches)} match(es)):\n{details}"
        )


def test_no_voseo_in_actions():
    """actions.py must contain zero voseo markers.

    RED: fails because error strings use 'elegí', 'Querés'.
    """
    assert _ACTIONS.exists(), f"File not found: {_ACTIONS}"
    matches = _find_voseo_matches(_ACTIONS)
    if matches:
        details = "\n".join(
            f"  Line {lineno}: pattern={pattern!r}  →  {text}" for lineno, pattern, text in matches
        )
        pytest.fail(
            f"Voseo markers found in {_ACTIONS.name} ({len(matches)} match(es)):\n{details}"
        )
