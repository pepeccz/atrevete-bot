"""Scenario F / R4.3 regression — Glossary phrase no-leak (HARD FAIL).

Tests that the FULL banned phrase "Y también te puedo dar la primera con disponibilidad"
does NOT appear anywhere in glossary.md OUTSIDE of <example do-not-reproduce> blocks.

IMPORTANT: The shorter substring "primera con disponibilidad" LEGITIMATELY appears
in instruction prose on line 88 of glossary.md (per W1 in PR-3 verify report) as
meta-instruction text — NOT as a reproducible example. This test asserts against the
FULL banned phrase, not the substring, to avoid false positives.

Also asserts that the <example do-not-reproduce> tags themselves are present and
properly closed.

This is a HARD FAIL test. No xfail.

Refs: spec R4.3, Scenario F, tasks 4.7, design §2 Slice 4, verify-report-pr3 W1
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

GLOSSARY_PATH = (
    Path(__file__).parent.parent.parent.parent  # project root
    / "agent"
    / "prompts"
    / "shared"
    / "glossary.md"
)

# The FULL banned phrase from spec R4.3 — do NOT use substrings.
# Per PR-3 verify W1: "primera con disponibilidad" (shorter) may appear legitimately
# in instruction prose; only the FULL sentence is the regression vector.
BANNED_FULL_PHRASE = "Y también te puedo dar la primera con disponibilidad"

# Tag delimiters for the do-not-reproduce block.
# We match BLOCK-OPENING tags: tags that appear at the START of a line (possibly with
# leading whitespace), not inline mentions inside code spans or prose.
# This avoids false-positive matches on lines like:
#   "NUNCA reproduzcas el texto dentro de `<example do-not-reproduce>` tal cual."
TAG_OPEN_PATTERN = re.compile(
    r"^[ \t]*<example\s+do-not-reproduce[^>]*>", re.IGNORECASE | re.MULTILINE
)
TAG_CLOSE = "</example>"


def _load_glossary() -> str:
    """Load glossary.md content. Fail test if file not found."""
    if not GLOSSARY_PATH.exists():
        pytest.fail(
            f"glossary.md not found at {GLOSSARY_PATH}. "
            "Verify PR-3 is merged and file path is correct."
        )
    return GLOSSARY_PATH.read_text(encoding="utf-8")


def _find_example_block_ranges(content: str) -> list[tuple[int, int]]:
    """Return list of (start_char, end_char) ranges for all <example do-not-reproduce> blocks."""
    ranges: list[tuple[int, int]] = []
    search_from = 0
    while True:
        m = TAG_OPEN_PATTERN.search(content, search_from)
        if not m:
            break
        start = m.start()
        close_idx = content.find(TAG_CLOSE, m.end())
        if close_idx == -1:
            # Unclosed tag — mark to end of file (conservative)
            ranges.append((start, len(content)))
            break
        end = close_idx + len(TAG_CLOSE)
        ranges.append((start, end))
        search_from = end
    return ranges


def _is_inside_example_block(pos: int, block_ranges: list[tuple[int, int]]) -> bool:
    """Return True if character position pos falls within any example block range."""
    return any(start <= pos < end for start, end in block_ranges)


# ---------------------------------------------------------------------------
# HARD FAIL assertions
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_example_do_not_reproduce_tags_present():
    """HARD FAIL: glossary.md must contain at least one <example do-not-reproduce> block."""
    content = _load_glossary()

    open_matches = list(TAG_OPEN_PATTERN.finditer(content))
    assert len(open_matches) >= 1, (
        "No <example do-not-reproduce> open tag found in glossary.md. "
        "Verify PR-3 Task 3.3 wrapped the stylist example in the do-not-reproduce block."
    )

    close_count = content.count(TAG_CLOSE)
    assert close_count >= 1, (
        "No </example> close tag found in glossary.md. "
        "The <example do-not-reproduce> block must be properly closed."
    )


@pytest.mark.integration
def test_example_block_is_properly_closed():
    """HARD FAIL: each <example do-not-reproduce> open tag has a matching </example> close."""
    content = _load_glossary()
    block_ranges = _find_example_block_ranges(content)

    open_count = len(list(TAG_OPEN_PATTERN.finditer(content)))
    close_count = content.count(TAG_CLOSE)

    assert open_count == close_count, (
        f"Mismatched example block tags: {open_count} open tag(s), "
        f"{close_count} close tag(s). All <example do-not-reproduce> blocks "
        "must be properly closed with </example>."
    )
    assert len(block_ranges) == open_count, (
        f"Could not parse all block ranges. Open tags: {open_count}, "
        f"parsed ranges: {len(block_ranges)}"
    )


@pytest.mark.integration
def test_banned_full_phrase_not_outside_example_block():
    """HARD FAIL: the FULL banned phrase must not appear outside <example do-not-reproduce> blocks.

    Per spec R4.3 and W1 from PR-3 verify report:
      - We assert the FULL phrase "Y también te puedo dar la primera con disponibilidad".
      - The shorter substring "primera con disponibilidad" may legitimately appear
        in instruction prose and is NOT asserted here (to avoid false positives).
    """
    content = _load_glossary()
    block_ranges = _find_example_block_ranges(content)

    search_from = 0
    violations: list[int] = []

    while True:
        idx = content.find(BANNED_FULL_PHRASE, search_from)
        if idx == -1:
            break
        if not _is_inside_example_block(idx, block_ranges):
            violations.append(idx)
        search_from = idx + len(BANNED_FULL_PHRASE)

    # If the phrase is absent entirely — that is also acceptable (PR-3 removed it)
    # The key invariant: it must NOT appear OUTSIDE the block.
    assert len(violations) == 0, (
        f"The phrase '{BANNED_FULL_PHRASE}' appears {len(violations)} time(s) "
        f"OUTSIDE <example do-not-reproduce> blocks. "
        f"Violation positions (char indices): {violations}. "
        "This is the regression that PR-3 Task 3.3 was designed to fix. "
        "Verify glossary.md wraps the stylist example in the do-not-reproduce block."
    )


@pytest.mark.integration
def test_example_block_contains_placeholder_content():
    """HARD FAIL: the <example do-not-reproduce> block must contain placeholder text."""
    content = _load_glossary()
    block_ranges = _find_example_block_ranges(content)

    assert len(block_ranges) >= 1, "No example blocks found (cannot verify placeholder content)"

    # Extract content of the first block and check for placeholder pattern
    start, end = block_ranges[0]
    block_content = content[start:end]

    has_placeholder = "{" in block_content and "}" in block_content
    assert has_placeholder, (
        f"The <example do-not-reproduce> block must contain template placeholders "
        f"(e.g., '{{nombre estilista 1}}'). Block content:\n{block_content}"
    )


@pytest.mark.integration
def test_substitution_instruction_present():
    """HARD FAIL: glossary.md must contain substitution instruction after the example block."""
    content = _load_glossary()

    # The substitution note should tell the LLM to replace placeholders with real data
    has_instruction = any(
        phrase in content
        for phrase in [
            "Sustituye",
            "payload.stylists",
            "NUNCA reproduzcas",
        ]
    )
    assert has_instruction, (
        "glossary.md must contain the substitution instruction after the example block "
        "(e.g., 'Sustituye los {placeholders} con los nombres reales...'). "
        "Verify PR-3 Task 3.3 added the guidance note."
    )
