"""
CI guard: assert zero voseo-form hits in production Python files.

Pattern covers the most common Argentine/Rioplatense voseo verb forms emitted
in customer-facing strings. Both present-indicative voseo (-és, -ás) and
voseo imperatives (-á, -í) are matched explicitly to avoid the false-positive
explosion of a generic accented-suffix pattern.

`sos` is intentionally excluded — word-boundary matching alone is insufficient
to avoid false positives in common Spanish compound identifiers.

Scope: agent/, api/, database/, shared/ — *.py files only.
Excludes .md files so R-1 quoted prohibited forms don't trigger false positives.
"""

from __future__ import annotations

import pathlib
import re

VOSEO_PATTERN = re.compile(
    r"\b("
    # Present-indicative voseo
    r"podés|querés|tenés|sabés|hacés|venís|comés|vivís|"
    # Voseo imperatives (accent on final vowel distinguishes from castellano)
    r"elegí|decime|contame|mostrá|enviá|escribí|"
    r"andá|mirá|dejá|fijate|tomá|hacé|vení|pasá|esperá|"
    r"buscá|llamá|probá|escuchá|dejame|olvidá|abrí|pedí|volvé|repetí"
    r")\b",
    re.IGNORECASE,
)
SCAN_DIRS = ["agent", "api", "database", "shared"]


def test_no_voseo_in_production_python() -> None:
    """REQ-VS-4: Zero voseo-pattern hits in production *.py files.

    FAILS with a human-readable message identifying file path and line number
    when any match is found. Runs in <1s (filesystem + regex only, no DB/Redis).
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for d in SCAN_DIRS:
        scan_path = repo_root / d
        if not scan_path.exists():
            continue
        for py in scan_path.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="replace")
            for m in VOSEO_PATTERN.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                offenders.append(f"{py.relative_to(repo_root)}:{line_no} — '{m.group(0)}'")
    assert not offenders, "Voseo found in production Python paths:\n" + "\n".join(offenders)
