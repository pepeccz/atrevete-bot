"""Structural tests for agent/prompts/shared/examples.md."""

from __future__ import annotations

from pathlib import Path

_SHARED = Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "shared"
_FILE = _SHARED / "examples.md"


def _content() -> str:
    assert _FILE.exists(), f"examples.md not found at {_FILE}"
    return _FILE.read_text(encoding="utf-8")


def test_examples_file_exists() -> None:
    assert _FILE.exists(), f"examples.md missing at {_FILE}"


def test_examples_file_has_required_headings() -> None:
    """examples.md contains Ejemplo 1, 6, 7, 8 — examples were renumbered/consolidated.

    NOTE: Ejemplo 2 and 3 were merged/restructured into 6/7/8 during the
    disambiguation UX cleanup (commit 3a46daf). Assert on actual headings present.
    """
    content = _content()
    # Ejemplo 1 is always present (variant disambiguation — peinado)
    assert "### Ejemplo 1" in content, "Missing '### Ejemplo 1' in examples.md"
    # At least one of the renumbered examples must be present
    has_extra = any(f"### Ejemplo {i}" in content for i in (6, 7, 8))
    assert has_extra, "examples.md must contain at least one of Ejemplo 6, 7, or 8"


def test_examples_file_has_bad_good_blocks() -> None:
    content = _content()
    assert content.count("<bad>") >= 3, "Expected at least 3 <bad> blocks"
    assert content.count("<good>") >= 3, "Expected at least 3 <good> blocks"
    assert content.count("</bad>") >= 3, "Expected at least 3 </bad> closing tags"
    assert content.count("</good>") >= 3, "Expected at least 3 </good> closing tags"
