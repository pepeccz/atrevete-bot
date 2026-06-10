"""T1 — I6: Assert qa_turn_helper CLI flags match SKILL.md documentation.

Spec: REQ-I6 / SC-I6-A, SC-I6-B, SC-I6-C
TDD: This test is written before the SKILL.md fix. It will fail until T2 applies the rename.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
SKILL_MD_PATH = PROJECT_ROOT / "skills" / "atrevete-qa-runner" / "SKILL.md"
QA_TURN_HELPER_PATH = PROJECT_ROOT / "tests" / "e2e" / "harness" / "qa_turn_helper.py"


def _get_skill_md_content() -> str:
    assert SKILL_MD_PATH.exists(), f"SKILL.md not found at {SKILL_MD_PATH}"
    return SKILL_MD_PATH.read_text(encoding="utf-8")


def _get_qa_turn_helper_content() -> str:
    assert QA_TURN_HELPER_PATH.exists(), f"qa_turn_helper.py not found at {QA_TURN_HELPER_PATH}"
    return QA_TURN_HELPER_PATH.read_text(encoding="utf-8")


def test_skill_md_uses_user_message_not_bare_message() -> None:
    """SC-I6-B: '--message' without the '--user-' prefix must NOT appear in SKILL.md.

    The parser declares '--user-message'; any occurrence of '--message' as a
    standalone flag (not part of '--user-message') is a documentation error.
    """
    content = _get_skill_md_content()
    # Find standalone '--message' that is NOT '--user-message'
    # Pattern: '--message' preceded by a non-word char or start, not preceded by 'user-'
    bad_occurrences = re.findall(r"(?<!\w)--message(?!-)", content)
    assert bad_occurrences == [], (
        f"SKILL.md contains {len(bad_occurrences)} occurrence(s) of standalone '--message'. "
        "The correct flag is '--user-message' as declared in qa_turn_helper.py _build_parser(). "
        "Apply the T2 rename to fix."
    )


def test_skill_md_contains_user_message_flag() -> None:
    """SC-I6-A: SKILL.md must document --user-message."""
    content = _get_skill_md_content()
    assert "--user-message" in content, (
        "SKILL.md does not contain '--user-message'. "
        "The qa_turn_helper.py parser uses '--user-message' (dest='user_message'). "
        "Update SKILL.md to match."
    )


def test_qa_turn_helper_declares_user_message_flag() -> None:
    """SC-I6-C: qa_turn_helper.py must declare --user-message (authoritative source)."""
    content = _get_qa_turn_helper_content()
    assert '"--user-message"' in content or "'--user-message'" in content, (
        "qa_turn_helper.py _build_parser() does not declare '--user-message'. "
        "The parser is the authoritative source for CLI flags."
    )


def test_skill_md_contains_other_flags() -> None:
    """SC-I6-C: Verify other documented flags remain present and correct."""
    content = _get_skill_md_content()
    expected_flags = ["--conversation-id", "--timeout"]
    for flag in expected_flags:
        assert flag in content, (
            f"SKILL.md is missing the expected flag '{flag}' after the rename. "
            "Only '--message' should have been renamed; other flags must remain."
        )
