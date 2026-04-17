"""
Unit tests for BookingModeNode.get_tools() visibility gate during audience ambiguity.

C3.2: check_availability must NOT appear in tool list when _audience_ambiguity is truthy,
even if has_services, has_stylist, and not has_slot all hold.

TDD cycle:
- Must FAIL before C3.3 (predicate not yet updated in get_tools).
- Must PASS after C3.3.

Covers: R7, S7.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.modes.booking_mode import BookingModeNode


# ---------------------------------------------------------------------------
# Node factory — minimal, no async I/O needed (get_tools is sync)
# ---------------------------------------------------------------------------


def _make_node() -> BookingModeNode:
    """Build a BookingModeNode with only the fields needed for get_tools()."""
    with patch("agent.modes.booking_mode.BaseModeNode.__init__", return_value=None):
        node = BookingModeNode.__new__(BookingModeNode)
    return node


def _tool_names(tools: list) -> list[str]:
    """Extract tool names from a list of tool objects."""
    return [t.name if hasattr(t, "name") else str(t) for t in tools]


# ---------------------------------------------------------------------------
# C3.2 — check_availability visibility gate
# ---------------------------------------------------------------------------


class TestGetToolsAudienceAmbiguityGate:
    """Unit tests for get_tools() predicate — _audience_ambiguity gates check_availability."""

    def test_check_availability_hidden_when_audience_ambiguity_set(self) -> None:
        """S7: check_availability must NOT appear when _audience_ambiguity is truthy.

        Even if has_services=True, has_stylist=True, has_slot=False — which would
        normally include check_availability — the presence of _audience_ambiguity
        must block it.

        FAILS on master because the predicate is:
            if has_services and has_stylist and not has_slot:
        and does not yet include `and not ctx.get("_audience_ambiguity")`.
        """
        node = _make_node()

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            # No selected_slot — so has_slot=False
            "_audience_ambiguity": {
                "family": "Corte",
                "variants": ["Corte Señora", "Corte Caballero"],
            },
        }

        tools = node.get_tools(ctx)
        names = _tool_names(tools)

        assert "check_availability" not in names, (
            f"check_availability must be HIDDEN when _audience_ambiguity is truthy. "
            f"Got tools: {names}. "
            "FAILS on master — predicate missing `and not ctx.get('_audience_ambiguity')`."
        )

    def test_check_availability_visible_without_audience_ambiguity(self) -> None:
        """Baseline: check_availability must appear when conditions are met and no ambiguity."""
        node = _make_node()

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            # No selected_slot, No _audience_ambiguity
        }

        tools = node.get_tools(ctx)
        names = _tool_names(tools)

        assert "check_availability" in names, (
            f"check_availability must be VISIBLE when services+stylist are set, "
            f"no slot, and no _audience_ambiguity. Got tools: {names}"
        )

    def test_check_availability_hidden_when_audience_ambiguity_falsy_empty_dict(self) -> None:
        """_audience_ambiguity={} (empty dict) is falsy — check_availability should appear."""
        node = _make_node()

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "_audience_ambiguity": {},  # empty dict — falsy in Python
        }

        tools = node.get_tools(ctx)
        names = _tool_names(tools)

        # Empty dict is falsy so check_availability should appear
        assert "check_availability" in names, (
            f"_audience_ambiguity={{}} is falsy — check_availability should be visible. "
            f"Got tools: {names}"
        )

    def test_update_booking_always_present(self) -> None:
        """update_booking must always be in the tool list regardless of context."""
        node = _make_node()

        ctx = {
            "_audience_ambiguity": {"family": "Corte", "variants": []},
        }

        tools = node.get_tools(ctx)
        names = _tool_names(tools)

        assert "update_booking" in names, (
            f"update_booking must always be present. Got tools: {names}"
        )

    def test_no_services_no_check_availability(self) -> None:
        """check_availability must not appear if last_services is empty."""
        node = _make_node()

        ctx = {
            "last_services": [],
            "last_stylist": "Maria",
        }

        tools = node.get_tools(ctx)
        names = _tool_names(tools)

        assert "check_availability" not in names, (
            f"check_availability should not appear without services. Got: {names}"
        )

    def test_audience_ambiguity_none_does_not_gate(self) -> None:
        """_audience_ambiguity=None (explicitly set to None) is falsy — should not gate."""
        node = _make_node()

        ctx = {
            "last_services": ["Corte Señora"],
            "last_stylist": "Maria",
            "_audience_ambiguity": None,
        }

        tools = node.get_tools(ctx)
        names = _tool_names(tools)

        assert "check_availability" in names, (
            f"_audience_ambiguity=None is falsy — check_availability should be visible. "
            f"Got tools: {names}"
        )
