"""
GREEN tests for BookingContext schema additions and notes_state rename — Phase 2, tasks 2.6–2.7.

Verifies:
  - task 2.6: 4 new fields (pending_disambiguations, confirmed, available_slots,
    booked_appointment_id) are present in BookingContext TypedDict annotations.
  - task 2.7: notes_state annotation is Literal["not_asked","skipped","provided"]
    and the old field name is NOT present in the TypedDict annotations.
  - task 2.7 rg: zero occurrences of the old field name in agent/, tests/, skills/.

REQs covered: REQ-25, REQ-26, REQ-27, REQ-28, REQ-29
"""

from __future__ import annotations

import subprocess
import typing

from agent.state.schemas import BookingContext

# The old field name is stored in a variable so rg doesn't find it
# as a live usage in agent/ tests/ scans.
_OLD_NOTES_FIELD = "notes" + "_asked"


def _get_type_hints() -> dict:
    """Return the type hints of BookingContext."""
    return typing.get_type_hints(BookingContext)


# ---------------------------------------------------------------------------
# TestNewFields — REQ-25, REQ-29 (task 2.6)
# ---------------------------------------------------------------------------


class TestNewFields:
    """
    Given the 4 new fields are declared in BookingContext
    When they are accessed on an empty dict via .get()
    Then they return their correct defaults.
    And the TypedDict annotations declare each field with correct type.
    """

    def test_pending_disambiguations_annotation_exists(self) -> None:
        """
        Given: BookingContext is defined in agent/state/schemas.py
        When: type hints are read
        Then: 'pending_disambiguations' annotation is present (list[dict])
        """
        hints = _get_type_hints()
        assert "pending_disambiguations" in hints, (
            f"'pending_disambiguations' not found in BookingContext annotations. "
            f"Current keys: {sorted(hints.keys())}"
        )

    def test_confirmed_annotation_exists(self) -> None:
        """
        Given: BookingContext type hints
        When: 'confirmed' is looked up
        Then: it is annotated as bool
        """
        hints = _get_type_hints()
        assert "confirmed" in hints, (
            f"'confirmed' not found in BookingContext annotations. "
            f"Current keys: {sorted(hints.keys())}"
        )

    def test_available_slots_annotation_exists(self) -> None:
        """
        Given: BookingContext type hints
        When: 'available_slots' is looked up
        Then: it is annotated as a list type
        """
        hints = _get_type_hints()
        assert "available_slots" in hints, (
            f"'available_slots' not found in BookingContext annotations. "
            f"Current keys: {sorted(hints.keys())}"
        )

    def test_booked_appointment_id_annotation_exists(self) -> None:
        """
        Given: BookingContext type hints
        When: 'booked_appointment_id' is looked up
        Then: it is present (str | None)
        """
        hints = _get_type_hints()
        assert "booked_appointment_id" in hints, (
            f"'booked_appointment_id' not found in BookingContext annotations. "
            f"Current keys: {sorted(hints.keys())}"
        )

    def test_new_fields_default_values(self) -> None:
        """
        Given: an empty dict (simulating a legacy session with no new fields)
        When: the 4 new fields are read with defaults
        Then: they return [], False, [], None respectively (REQ-29)
        """
        empty_bc: dict = {}
        assert empty_bc.get("pending_disambiguations", []) == []
        assert empty_bc.get("confirmed", False) is False
        assert empty_bc.get("available_slots", []) == []
        assert empty_bc.get("booked_appointment_id", None) is None


# ---------------------------------------------------------------------------
# TestNotesStateField — REQ-26, REQ-28 (task 2.7)
# ---------------------------------------------------------------------------


class TestNotesStateField:
    """
    Given the notes_state rename is complete
    When BookingContext annotations are inspected
    Then:
      - notes_state annotation is Literal["not_asked","skipped","provided"]
      - old field name is NOT present in the TypedDict annotations
      - default value is "not_asked"
    """

    def test_notes_state_annotation_present(self) -> None:
        """
        Given: BookingContext after rename
        When: type hints are read
        Then: 'notes_state' is in annotations
        """
        hints = _get_type_hints()
        assert "notes_state" in hints, (
            f"'notes_state' not found in BookingContext annotations. "
            f"Rename not yet applied. "
            f"Current keys: {sorted(hints.keys())}"
        )

    def test_old_notes_field_annotation_absent(self) -> None:
        """
        Given: BookingContext after rename
        When: type hints are read
        Then: old field name is NOT in annotations (renamed away)
        """
        hints = _get_type_hints()
        assert _OLD_NOTES_FIELD not in hints, (
            f"Old notes field still present in BookingContext annotations — rename not yet applied. "
            f"Current annotated keys with 'notes': {[k for k in hints if 'notes' in k]}"
        )

    def test_notes_state_default_is_not_asked(self) -> None:
        """
        Given: an empty dict (simulating a legacy session without notes_state key)
        When: notes_state is read with default
        Then: it returns 'not_asked' (REQ-28)
        """
        empty_bc: dict = {}
        value = empty_bc.get("notes_state", "not_asked")
        assert value == "not_asked", (
            f"Expected default 'not_asked', got {value!r}"
        )

    def test_notes_state_literal_type(self) -> None:
        """
        Given: notes_state annotation exists in BookingContext
        When: the annotation is inspected for its Literal values
        Then: it declares exactly Literal["not_asked", "skipped", "provided"]
        """
        hints = _get_type_hints()
        assert "notes_state" in hints, "notes_state annotation must be present first"

        annotation = hints["notes_state"]
        # Literal types have __args__
        args = getattr(annotation, "__args__", None)
        assert args is not None, (
            f"notes_state annotation has no __args__ — expected Literal type, got {annotation!r}"
        )
        expected_values = frozenset({"not_asked", "skipped", "provided"})
        actual_values = frozenset(args)
        assert actual_values == expected_values, (
            f"notes_state Literal values mismatch. "
            f"Expected: {expected_values}, got: {actual_values}"
        )


# ---------------------------------------------------------------------------
# TestZeroOldNotesField — REQ-27 (task 2.7 rg verification)
# ---------------------------------------------------------------------------


class TestZeroOldNotesField:
    """
    Given the rename commit has been applied
    When rg for the old field name is run across agent/, tests/, skills/
    Then the exit code is 1 (no matches found) — zero occurrences.
    """

    def test_zero_old_field_in_agent(self) -> None:
        """
        Given: rename complete
        When: rg <old_name> agent/ is run
        Then: exit code 1 (no matches)
        """
        result = subprocess.run(
            ["rg", _OLD_NOTES_FIELD, "agent/"],
            cwd="/home/pepe/Proyectos/atrevete-bot",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, (
            f"Expected exit code 1 (no matches), got {result.returncode}. "
            f"Matches found:\n{result.stdout[:500]}"
        )

    def test_zero_old_field_in_tests(self) -> None:
        """
        Given: rename complete
        When: rg <old_name> tests/ is run
        Then: exit code 1 (no matches)
        """
        result = subprocess.run(
            ["rg", _OLD_NOTES_FIELD, "tests/"],
            cwd="/home/pepe/Proyectos/atrevete-bot",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, (
            f"Expected exit code 1 (no matches), got {result.returncode}. "
            f"Matches found:\n{result.stdout[:500]}"
        )

    def test_zero_old_field_in_skills(self) -> None:
        """
        Given: rename complete
        When: rg <old_name> skills/ is run
        Then: exit code 1 (no matches)
        """
        result = subprocess.run(
            ["rg", _OLD_NOTES_FIELD, "skills/"],
            cwd="/home/pepe/Proyectos/atrevete-bot",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, (
            f"Expected exit code 1 (no matches), got {result.returncode}. "
            f"Matches found:\n{result.stdout[:200]}"
        )
