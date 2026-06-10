"""Tests for AS10 and AS11: new QA skills present, old ones absent, AGENTS.md consistent."""

from __future__ import annotations

from pathlib import Path

import pytest

# Root of the repository (two levels above tests/unit/)
REPO_ROOT = Path(__file__).parent.parent.parent

SKILLS_DIR = REPO_ROOT / "skills"
AGENTS_MD = REPO_ROOT / "AGENTS.md"


# ---------------------------------------------------------------------------
# AS10 — Old skill directories must be absent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "old_skill",
    [
        "atrevete-qa-context",
        "atrevete-qa-tester",
        "atrevete-qa-evaluator",
    ],
)
def test_old_skill_directory_absent(old_skill: str) -> None:
    """Old QA skill directories must not exist after PR-3 cleanup."""
    skill_dir = SKILLS_DIR / old_skill
    assert not skill_dir.exists(), (
        f"Old skill directory still present: {skill_dir}. "
        "Run T3.4 to delete it."
    )


@pytest.mark.parametrize(
    "old_skill",
    [
        "atrevete-qa-context",
        "atrevete-qa-tester",
        "atrevete-qa-evaluator",
    ],
)
def test_old_skill_md_absent(old_skill: str) -> None:
    """Old QA SKILL.md files must not exist after PR-3 cleanup."""
    skill_md = SKILLS_DIR / old_skill / "SKILL.md"
    assert not skill_md.exists(), (
        f"Old SKILL.md still present: {skill_md}. "
        "Run T3.4 to delete it."
    )


# ---------------------------------------------------------------------------
# AS10 — New skill directories must be present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "new_skill",
    [
        "atrevete-qa-runner",
        "atrevete-qa-auditor",
    ],
)
def test_new_skill_md_present(new_skill: str) -> None:
    """New QA SKILL.md files must exist after PR-3."""
    skill_md = SKILLS_DIR / new_skill / "SKILL.md"
    assert skill_md.exists(), (
        f"New SKILL.md not found: {skill_md}. "
        "Run T3.2/T3.3 to create it."
    )
    assert skill_md.stat().st_size > 0, f"SKILL.md is empty: {skill_md}"


# ---------------------------------------------------------------------------
# AS11 — AGENTS.md must not reference old skills
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "old_ref",
    [
        "atrevete-qa-context",
        "atrevete-qa-tester",
        "atrevete-qa-evaluator",
    ],
)
def test_agents_md_no_old_skill_refs(old_ref: str) -> None:
    """AGENTS.md must not contain any reference to old QA skills."""
    content = AGENTS_MD.read_text()
    assert old_ref not in content, (
        f"AGENTS.md still references '{old_ref}'. "
        "Run T3.5 to remove it."
    )


# ---------------------------------------------------------------------------
# AS11 — AGENTS.md must reference new skills at least twice each
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "new_ref",
    [
        "atrevete-qa-runner",
        "atrevete-qa-auditor",
    ],
)
def test_agents_md_has_new_skill_refs(new_ref: str) -> None:
    """AGENTS.md must contain at least 2 references to each new QA skill."""
    content = AGENTS_MD.read_text()
    count = content.count(new_ref)
    assert count >= 2, (
        f"AGENTS.md contains only {count} reference(s) to '{new_ref}' "
        f"(expected >= 2). Run T3.5 to add entries."
    )


# ---------------------------------------------------------------------------
# Content sanity — new skills must reference current architecture
# ---------------------------------------------------------------------------


def test_qa_runner_skill_references_agent_factory() -> None:
    """atrevete-qa-runner SKILL.md must reference the current agent_factory SSOT."""
    skill_md = SKILLS_DIR / "atrevete-qa-runner" / "SKILL.md"
    if not skill_md.exists():
        pytest.skip("atrevete-qa-runner/SKILL.md not yet created")
    content = skill_md.read_text()
    assert "agent_factory" in content, (
        "Runner skill must reference agent_factory.py (current architecture SSOT)."
    )


def test_qa_runner_skill_no_mode_references() -> None:
    """atrevete-qa-runner SKILL.md must not direct users to deleted mode-based artifacts.

    We check that mode references only appear in explicit 'do NOT' prohibition
    sentences, not as positive instructions. The skill should never say 'read
    agent/modes/' or 'use current_mode' as a positive directive.
    """
    skill_md = SKILLS_DIR / "atrevete-qa-runner" / "SKILL.md"
    if not skill_md.exists():
        pytest.skip("atrevete-qa-runner/SKILL.md not yet created")
    content = skill_md.read_text()
    # These phrases would indicate the skill is directing users to the old architecture
    positive_mode_refs = [
        "read agent/modes/",
        "see agent/modes/",
        "use current_mode",
        "check mode_context",
        "check mode_history",
        "check booking_step",
    ]
    for term in positive_mode_refs:
        assert term not in content, (
            f"Runner skill positively references deleted artifact: '{term}'. "
            "Remove all positive mode-based references."
        )


def test_qa_auditor_skill_references_agent_factory() -> None:
    """atrevete-qa-auditor SKILL.md must reference the current agent_factory SSOT."""
    skill_md = SKILLS_DIR / "atrevete-qa-auditor" / "SKILL.md"
    if not skill_md.exists():
        pytest.skip("atrevete-qa-auditor/SKILL.md not yet created")
    content = skill_md.read_text()
    assert "agent_factory" in content, (
        "Auditor skill must reference agent_factory.py (current architecture SSOT)."
    )


def test_qa_auditor_skill_no_mode_references() -> None:
    """atrevete-qa-auditor SKILL.md must not direct users to deleted mode-based artifacts.

    The skill may mention these terms in 'do NOT reference' prohibition notes,
    but must never use them as positive investigation targets.
    """
    skill_md = SKILLS_DIR / "atrevete-qa-auditor" / "SKILL.md"
    if not skill_md.exists():
        pytest.skip("atrevete-qa-auditor/SKILL.md not yet created")
    content = skill_md.read_text()
    # These phrases would indicate the skill is directing users to the old architecture
    positive_mode_refs = [
        "read agent/modes/",
        "see agent/modes/",
        "use current_mode",
        "check mode_context",
        "check mode_history",
        "use BaseModeNode",
        "agent/modes/greeting_mode",
        "agent/modes/booking_mode",
        "agent/modes/general_mode",
    ]
    for term in positive_mode_refs:
        assert term not in content, (
            f"Auditor skill positively references deleted artifact: '{term}'. "
            "Remove all positive mode-based references."
        )


def test_qa_runner_skill_canonical_outcome_enum() -> None:
    """Runner skill must document the canonical outcome enum."""
    skill_md = SKILLS_DIR / "atrevete-qa-runner" / "SKILL.md"
    if not skill_md.exists():
        pytest.skip("atrevete-qa-runner/SKILL.md not yet created")
    content = skill_md.read_text()
    # Must contain the canonical outcome enum values
    for outcome in ["booked", "cancelled", "rescheduled", "escalated", "policy_accepted", "timeout", "error"]:
        assert outcome in content, (
            f"Runner skill must document canonical outcome enum value: '{outcome}'."
        )


def test_qa_auditor_skill_canonical_outcome_enum() -> None:
    """Auditor skill must document the canonical outcome enum."""
    skill_md = SKILLS_DIR / "atrevete-qa-auditor" / "SKILL.md"
    if not skill_md.exists():
        pytest.skip("atrevete-qa-auditor/SKILL.md not yet created")
    content = skill_md.read_text()
    for outcome in ["booked", "cancelled", "rescheduled", "escalated", "policy_accepted", "timeout", "error"]:
        assert outcome in content, (
            f"Auditor skill must document canonical outcome enum value: '{outcome}'."
        )
