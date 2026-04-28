"""
T6 — Agent factory wiring: update_booking must be in AGENT_TOOLS.

Asserts:
- AGENT_TOOLS contains exactly 6 tools.
- A tool named "update_booking" is present.
- The original 5 tools are still present.
"""

import pytest

EXPECTED_TOOL_NAMES = {
    "check_availability",
    "get_next_available_options",
    "book",
    "manage_appointments",
    "escalate",
    "update_booking",
}


def test_agent_tools_count():
    """AGENT_TOOLS must have exactly 6 tools after wiring update_booking."""
    from agent.tools import AGENT_TOOLS

    assert len(AGENT_TOOLS) == 6, (
        f"Expected 6 tools in AGENT_TOOLS, got {len(AGENT_TOOLS)}: "
        f"{[t.name for t in AGENT_TOOLS]}"
    )


def test_update_booking_registered():
    """update_booking must be present in AGENT_TOOLS by name."""
    from agent.tools import AGENT_TOOLS

    names = {t.name for t in AGENT_TOOLS}
    assert "update_booking" in names, (
        f"'update_booking' not found in AGENT_TOOLS. Present tools: {sorted(names)}"
    )


def test_original_tools_still_present():
    """The original 5 tools must remain registered (no regressions)."""
    from agent.tools import AGENT_TOOLS

    names = {t.name for t in AGENT_TOOLS}
    original = EXPECTED_TOOL_NAMES - {"update_booking"}
    missing = original - names
    assert not missing, (
        f"Original tools removed from AGENT_TOOLS: {missing}. Present: {sorted(names)}"
    )


def test_all_expected_tools_present():
    """AGENT_TOOLS must contain exactly the expected 6 tool names."""
    from agent.tools import AGENT_TOOLS

    names = {t.name for t in AGENT_TOOLS}
    assert names == EXPECTED_TOOL_NAMES, (
        f"AGENT_TOOLS mismatch.\n  Expected: {sorted(EXPECTED_TOOL_NAMES)}\n  Got: {sorted(names)}"
    )
