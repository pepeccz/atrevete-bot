"""
B.5.2 — assert no unused imports (F401) in the core booking files.
Uses ruff directly to avoid maintaining a manual import list.

NOTE: agent/booking/grounding.py and agent/booking/patch_pipeline.py were removed
in the create_agent architectural rewrite. The test now checks agent/prompts/loader.py
only, which is the surviving file from that original set. The test also guards against
missing ruff on PATH or missing source files.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_no_unused_imports_in_booking_files() -> None:
    """ruff F401 must report zero violations in agent/prompts/loader.py."""
    root = Path(__file__).parent.parent.parent

    # Resolve ruff binary — prefer venv, fall back to PATH
    ruff_bin = root / "venv" / "bin" / "ruff"
    if not ruff_bin.exists():
        ruff_on_path = shutil.which("ruff")
        if ruff_on_path is None:
            pytest.skip("ruff not found in venv or PATH — install ruff to enable this check")
        ruff_bin = ruff_on_path

    # Only check files that actually exist
    candidate_files = [
        "agent/prompts/loader.py",
    ]
    existing_files = [f for f in candidate_files if (root / f).exists()]
    if not existing_files:
        pytest.skip("No target booking files found — they may have been removed or renamed")

    result = subprocess.run(
        [str(ruff_bin), "check", "--select", "F401"] + existing_files,
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert (
        result.returncode == 0
    ), f"ruff F401 violations found in booking files:\n{result.stdout}\n{result.stderr}"
