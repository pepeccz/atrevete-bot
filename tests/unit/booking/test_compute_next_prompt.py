"""
RED tests for agent/booking/grounding.py::compute_next_prompt — Phase 1, tasks 1.7–1.10.

Expected fail mode: ModuleNotFoundError: No module named 'agent.booking'
(implementation does not exist yet — this is the expected TDD RED signal).

REQs covered: REQ-21, REQ-22, REQ-23, REQ-24
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

# This import will raise ModuleNotFoundError in RED phase.
# Do NOT add @pytest.mark.xfail — the failure IS the test signal.
from agent.booking.grounding import compute_next_prompt


# Closed set of valid actions per REQ-9 / design §3
VALID_ACTIONS = frozenset(
    {
        "BOOKING_COMPLETE",
        "CALL_BOOK",
        "AWAIT_CONFIRMATION",
        "ASK_AUDIENCE",
        "ASK_SERVICE",
        "ASK_MORE_SERVICES",
        "ASK_STYLIST",
        "ASK_AVAILABILITY",
        "ASK_SLOT",
        "ASK_NAME",
        "ASK_NOTES",
        "SHOW_CONFIRMATION",
        "ERROR_RECOVERY",
    }
)


# ---------------------------------------------------------------------------
# TestComputeNextPromptBranches — REQ-21, REQ-22, REQ-24 (task 1.7)
# ---------------------------------------------------------------------------


class TestComputeNextPromptBranches:
    """
    Parametrised coverage of all 13 decision-tree branches.

    Given: a BookingContext fixture satisfying exactly one branch condition
    When: compute_next_prompt(state) is called
    Then: the returned GroundingInstruction.action matches the expected value
    """

    @pytest.mark.parametrize(
        "fixture_name,expected_action",
        [
            ("bc_branch_1_completed", "BOOKING_COMPLETE"),
            ("bc_branch_2_confirmed", "CALL_BOOK"),
            ("bc_branch_3_await_confirmation", "AWAIT_CONFIRMATION"),
            ("bc_branch_4_disambig", "ASK_AUDIENCE"),
            ("bc_branch_5_no_services", "ASK_SERVICE"),
            ("bc_branch_6_ask_more", "ASK_MORE_SERVICES"),
            ("bc_branch_7_ask_stylist", "ASK_STYLIST"),
            ("bc_branch_8_ask_availability", "ASK_AVAILABILITY"),
            ("bc_branch_9_ask_slot", "ASK_SLOT"),
            ("bc_branch_10_ask_name", "ASK_NAME"),
            ("bc_branch_11_ask_notes", "ASK_NOTES"),
            ("bc_branch_12_show_confirmation", "SHOW_CONFIRMATION"),
            ("bc_branch_13_error_recovery", "ERROR_RECOVERY"),
        ],
    )
    def test_branch_action(self, request: pytest.FixtureRequest, fixture_name: str, expected_action: str) -> None:
        """
        Given: a fixture satisfying exactly one branch condition
        When: compute_next_prompt is called with the fixture as booking_context
        Then: directive.action equals the expected action for that branch
        """
        bc = request.getfixturevalue(fixture_name)
        state = {"booking_context": bc, "current_mode": "BOOKING"}
        directive = compute_next_prompt(state)
        assert directive.action == expected_action, (
            f"Branch {fixture_name}: expected action={expected_action!r}, "
            f"got action={directive.action!r}. Reason: {directive.reason!r}"
        )


# ---------------------------------------------------------------------------
# TestDeterminism — REQ-21, REQ-23 (task 1.8)
# ---------------------------------------------------------------------------


class TestDeterminism:
    """
    Given a fixed BookingContext dict
    When compute_next_prompt is called 10 times in sequence
    Then all calls return the same .action and .reason
    """

    def test_same_input_same_output(self, bc_branch_7_ask_stylist: dict) -> None:
        """
        Given: a frozen BookingContext fixture
        When: compute_next_prompt is called 10 times with the same input
        Then: all returned actions and reasons are identical
        """
        state = {"booking_context": bc_branch_7_ask_stylist, "current_mode": "BOOKING"}
        results = [compute_next_prompt(state) for _ in range(10)]
        actions = {r.action for r in results}
        reasons = {r.reason for r in results}
        assert len(actions) == 1, f"Non-deterministic actions: {actions}"
        assert len(reasons) == 1, f"Non-deterministic reasons: {reasons}"

    def test_determinism_across_all_branches(
        self,
        bc_branch_1_completed: dict,
        bc_branch_5_no_services: dict,
        bc_branch_12_show_confirmation: dict,
    ) -> None:
        """
        Given: multiple branch fixtures
        When: each is called 5 times
        Then: each produces consistent output
        """
        for bc in [bc_branch_1_completed, bc_branch_5_no_services, bc_branch_12_show_confirmation]:
            state = {"booking_context": bc, "current_mode": "BOOKING"}
            results = [compute_next_prompt(state) for _ in range(5)]
            actions = {r.action for r in results}
            assert len(actions) == 1, f"Non-deterministic for bc={bc}: {actions}"


# ---------------------------------------------------------------------------
# TestGroundingInstructionShape — REQ-24, REQ-9 (task 1.9)
# ---------------------------------------------------------------------------


class TestGroundingInstructionShape:
    """
    Given compute_next_prompt returns a GroundingInstruction
    When the fields are accessed
    Then .action, .reason, .data are accessible with correct types
    """

    def test_has_action_field(self, bc_branch_6_ask_more: dict) -> None:
        """
        Given: compute_next_prompt returns a GroundingInstruction
        When: .action is accessed
        Then: no AttributeError is raised
        """
        state = {"booking_context": bc_branch_6_ask_more, "current_mode": "BOOKING"}
        directive = compute_next_prompt(state)
        _ = directive.action  # must not raise

    def test_has_reason_field_nonempty(self, bc_branch_6_ask_more: dict) -> None:
        """
        Given: compute_next_prompt returns a GroundingInstruction
        When: .reason is accessed
        Then: it is a non-empty string
        """
        state = {"booking_context": bc_branch_6_ask_more, "current_mode": "BOOKING"}
        directive = compute_next_prompt(state)
        assert isinstance(directive.reason, str), (
            f"Expected str reason, got {type(directive.reason).__name__}"
        )
        assert len(directive.reason) > 0, "reason must be non-empty"

    def test_has_data_field_as_dict(self, bc_branch_6_ask_more: dict) -> None:
        """
        Given: compute_next_prompt returns a GroundingInstruction
        When: .data is accessed
        Then: it is a dict (may be empty)
        """
        state = {"booking_context": bc_branch_6_ask_more, "current_mode": "BOOKING"}
        directive = compute_next_prompt(state)
        assert isinstance(directive.data, dict), (
            f"Expected dict data, got {type(directive.data).__name__}"
        )

    def test_action_is_in_closed_set(self, bc_branch_9_ask_slot: dict) -> None:
        """
        Given: compute_next_prompt returns a GroundingInstruction
        When: .action is read
        Then: its value is one of the 13 closed-set literals (REQ-9)
        """
        state = {"booking_context": bc_branch_9_ask_slot, "current_mode": "BOOKING"}
        directive = compute_next_prompt(state)
        assert directive.action in VALID_ACTIONS, (
            f"action={directive.action!r} is not in the valid closed set: {VALID_ACTIONS}"
        )

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "bc_branch_1_completed",
            "bc_branch_5_no_services",
            "bc_branch_12_show_confirmation",
        ],
    )
    def test_all_branches_produce_valid_action(
        self, request: pytest.FixtureRequest, fixture_name: str
    ) -> None:
        """
        Given: any branch fixture
        When: compute_next_prompt is called
        Then: the resulting .action is in the closed 13-value set
        """
        bc = request.getfixturevalue(fixture_name)
        state = {"booking_context": bc, "current_mode": "BOOKING"}
        directive = compute_next_prompt(state)
        assert directive.action in VALID_ACTIONS, (
            f"{fixture_name}: action {directive.action!r} not in closed set"
        )


# ---------------------------------------------------------------------------
# TestNoIO — REQ-23 (task 1.10)
# ---------------------------------------------------------------------------


class TestNoIO:
    """
    Given compute_next_prompt is a pure function
    When it is called with any BookingContext
    Then no network I/O occurs (socket connections are forbidden)
    """

    def test_no_network_io(self, bc_branch_11_ask_notes: dict) -> None:
        """
        Given: socket.socket is patched to raise on connect
        When: compute_next_prompt is called
        Then: no exception propagates (the function never tries to connect)
        """
        original_connect = socket.socket.connect

        def _raise_on_connect(*args, **kwargs):
            raise ConnectionError("Network I/O is forbidden in pure function compute_next_prompt")

        state = {"booking_context": bc_branch_11_ask_notes, "current_mode": "BOOKING"}

        with patch.object(socket.socket, "connect", _raise_on_connect):
            # Should complete without raising — pure function, no I/O
            directive = compute_next_prompt(state)
            assert directive.action in VALID_ACTIONS

    def test_no_io_across_multiple_branches(
        self,
        bc_branch_2_confirmed: dict,
        bc_branch_8_ask_availability: dict,
    ) -> None:
        """
        Given: socket patched to forbid connections
        When: compute_next_prompt is called for multiple branch fixtures
        Then: no exception from network access
        """

        def _raise(*args, **kwargs):
            raise ConnectionError("I/O forbidden")

        with patch.object(socket.socket, "connect", _raise):
            for bc in [bc_branch_2_confirmed, bc_branch_8_ask_availability]:
                state = {"booking_context": bc, "current_mode": "BOOKING"}
                directive = compute_next_prompt(state)
                assert directive.action in VALID_ACTIONS
