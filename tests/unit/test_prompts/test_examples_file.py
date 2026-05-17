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


def test_examples_file_has_three_headings() -> None:
    content = _content()
    for i in (1, 2, 3):
        assert f"### Ejemplo {i}" in content, f"Missing '### Ejemplo {i}' in examples.md"


def test_examples_file_has_bad_good_blocks() -> None:
    content = _content()
    assert content.count("<bad>") >= 3, "Expected at least 3 <bad> blocks"
    assert content.count("<good>") >= 3, "Expected at least 3 <good> blocks"
    assert content.count("</bad>") >= 3, "Expected at least 3 </bad> closing tags"
    assert content.count("</good>") >= 3, "Expected at least 3 </good> closing tags"
