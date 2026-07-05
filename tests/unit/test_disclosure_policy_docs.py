"""sdd/context-coherence TASK-16 — per-thread disclosure policy documentation.

Requirement: Per-Thread Disclosure Policy Documentation (D9, Q3). No code
change to DisclosureMiddleware — it keeps firing per-thread by design (EU AI
Act). This test only pins that the policy and its rationale are documented
in the two canonical locations the design specifies.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
AGENT_AGENTS_MD = PROJECT_ROOT / "agent" / "AGENTS.md"
RESILIENCE_DOC = PROJECT_ROOT / "docs" / "system" / "07-resilience.md"


def test_agent_agents_md_documents_disclosure_per_thread_policy() -> None:
    text = AGENT_AGENTS_MD.read_text(encoding="utf-8")
    assert (
        "per-thread" in text.lower() or "por hilo" in text.lower()
    ), "agent/AGENTS.md must document that DisclosureMiddleware fires per-thread"
    assert "DisclosureMiddleware" in text


def test_agent_agents_md_explains_new_threads_become_rare() -> None:
    """Q3 rationale: Stream 1 threading fix makes new threads rare, not the suppression."""
    text = AGENT_AGENTS_MD.read_text(encoding="utf-8")
    assert (
        "context-coherence" in text
    ), "agent/AGENTS.md disclosure policy note must reference sdd/context-coherence"


def test_resilience_doc_references_disclosure_policy() -> None:
    text = RESILIENCE_DOC.read_text(encoding="utf-8")
    assert (
        "disclosure" in text.lower()
    ), "docs/system/07-resilience.md must reference the disclosure per-thread policy"
