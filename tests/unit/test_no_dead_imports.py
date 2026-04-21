"""
B.5.2 — assert no unused imports (F401) in the core booking files modified by
B.1–B.5.  Uses ruff directly to avoid maintaining a manual import list.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_BOOKING_FILES = [
    "agent/booking/grounding.py",
    "agent/booking/patch_pipeline.py",
    "agent/prompts/loader.py",
]


def test_no_unused_imports_in_booking_files() -> None:
    """ruff F401 must report zero violations across the 5 core booking files."""
    root = Path(__file__).parent.parent.parent
    ruff_bin = root / "venv" / "bin" / "ruff"
    if not ruff_bin.exists():
        ruff_bin = "ruff"  # fall back to PATH

    result = subprocess.run(
        [str(ruff_bin), "check", "--select", "F401"] + _BOOKING_FILES,
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert (
        result.returncode == 0
    ), f"ruff F401 violations found in booking files:\n{result.stdout}\n{result.stderr}"
