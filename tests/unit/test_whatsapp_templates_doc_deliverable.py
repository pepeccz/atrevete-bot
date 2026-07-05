"""sdd/context-coherence TASK-19 — proposed corrected ~24h reminder template copy.

Pins the deliverable: docs/whatsapp-templates.md must carry a 4-placeholder,
gated-flip-documented replacement for the old 3-var/hardcoded-"mañana" body,
distinct from the countdown-style copy of the live-misconfigured template
(system_settings.whatsapp_template_reminder_24h currently points at a 2h
handler's "En 2 horas..." copy — see docs/system, obs #7491 finding 5).
"""

from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).parent.parent.parent / "docs" / "whatsapp-templates.md"


def _doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_exists() -> None:
    assert DOC_PATH.exists()


def test_proposed_copy_has_four_placeholders() -> None:
    text = _doc()
    for i in range(1, 5):
        assert f"{{{{{i}}}}}" in text, f"Expected placeholder {{{{{i}}}}} in proposed reminder copy"


def test_proposed_copy_does_not_hardcode_manana() -> None:
    """The corrected copy must use {{2}} for the date, not a hardcoded 'mañana'."""
    text = _doc()
    start = text.find("Hola {{1}} 🌸 Te recordamos")
    assert start >= 0, "Corrected reminder copy not found"
    line = text[start : text.find("\n", start)]
    assert "mañana" not in line.lower()


def test_gated_flip_is_documented() -> None:
    text = _doc()
    assert "GATEADO" in text or "gateado" in text.lower()
    assert "engram #7493" in text or "Q4" in text
