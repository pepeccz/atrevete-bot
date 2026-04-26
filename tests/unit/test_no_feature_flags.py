"""T8.a — sentinel: no USE_CAPABILITY_BOOKING feature flag in agent/.

R-IDs: R15
"""
from __future__ import annotations

import subprocess
from pathlib import Path

AGENT_DIR = Path(__file__).parent.parent.parent / "agent"


def test_no_feature_flag() -> None:
    """Assert no feature-flag string exists anywhere under agent/."""
    patterns = [
        "USE_CAPABILITY_BOOKING",
        "CAPABILITY_BOOKING",
        "booking_flag",
    ]
    agent_py_files = list(AGENT_DIR.rglob("*.py"))
    for path in agent_py_files:
        source = path.read_text(encoding="utf-8")
        for pattern in patterns:
            assert pattern not in source, (
                f"Feature flag '{pattern}' found in {path}. "
                "Remove feature flags — design requires stateless tool contract."
            )
