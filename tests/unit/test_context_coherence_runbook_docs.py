"""sdd/context-coherence TASK-20 — deploy runbook + Langfuse credential-regen step.

Requirement: Reminder Template Correction (Gated) — the flip must remain
documented as a blocked dependency, not executed. Requirement: Langfuse
Credential Runbook — a manual runbook step must exist.
"""

from __future__ import annotations

from pathlib import Path

CLAUDE_MD = Path(__file__).parent.parent.parent / "CLAUDE.md"


def _text() -> str:
    return CLAUDE_MD.read_text(encoding="utf-8")


def test_context_coherence_runbook_section_exists() -> None:
    text = _text()
    assert "Deploy Runbook (context-coherence prompts" in text


def test_runbook_documents_gated_flip_not_executed() -> None:
    text = _text()
    start = text.find("Deploy Runbook (context-coherence prompts")
    assert start >= 0
    section = text[start : start + 4000]
    assert "DO NOT FLIP YET" in section
    assert "whatsapp_template_reminder_24h" in section


def test_runbook_documents_langfuse_credential_regeneration() -> None:
    text = _text()
    start = text.find("Deploy Runbook (context-coherence prompts")
    assert start >= 0
    section = text[start : start + 6000]
    assert "LANGFUSE_PUBLIC_KEY" in section
    assert "LANGFUSE_SECRET_KEY" in section
    assert "restart" in section.lower()
