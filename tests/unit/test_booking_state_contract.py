"""
Unit tests for the State Authority Registry (agent/booking/state_contract.py).

REQ-1..4: registry exists, covers all BookingContext fields, and exposes
          BOOKING_STATE_AUTHORITY + FIELD_WRITERS + FIELD_READERS.
REQ-12..14: BookingContext does NOT contain dead fields after Phase 4 purge.

Test execution order matters — Phase 1 tests are marked with `phase1` and
Phase 4 tests with `phase4` so they can be run in isolation during development.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Phase 1 — State Authority Registry
# ---------------------------------------------------------------------------


class TestStateAuthorityRegistryExists:
    """REQ-1: state_contract module exports the required names."""

    def test_module_importable(self) -> None:
        """state_contract.py must exist and be importable."""
        from agent.booking import state_contract  # noqa: F401

    def test_exports_booking_state_authority(self) -> None:
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY

        assert isinstance(BOOKING_STATE_AUTHORITY, dict), "BOOKING_STATE_AUTHORITY must be a dict"

    def test_exports_field_writers(self) -> None:
        from agent.booking.state_contract import FIELD_WRITERS

        assert isinstance(FIELD_WRITERS, dict), "FIELD_WRITERS must be a dict"

    def test_exports_field_readers(self) -> None:
        from agent.booking.state_contract import FIELD_READERS

        assert isinstance(FIELD_READERS, dict), "FIELD_READERS must be a dict"

    def test_exports_compute_state_for_grounding(self) -> None:
        from agent.booking.state_contract import compute_state_for_grounding

        assert callable(compute_state_for_grounding)


class TestRegistryCoversAllAnnotations:
    """REQ-4: every BookingContext field must appear in BOOKING_STATE_AUTHORITY."""

    def test_every_annotation_in_registry(self) -> None:
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY
        from agent.state.schemas import BookingContext

        annotations = set(BookingContext.__annotations__.keys())
        registry_keys = set(BOOKING_STATE_AUTHORITY.keys())

        missing = annotations - registry_keys
        assert not missing, (
            f"Fields in BookingContext but NOT in BOOKING_STATE_AUTHORITY: {missing}\n"
            "Add entries to agent/booking/state_contract.py"
        )

    def test_no_extra_registry_entries(self) -> None:
        """Registry should not declare fields that no longer exist in BookingContext."""
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY
        from agent.state.schemas import BookingContext

        annotations = set(BookingContext.__annotations__.keys())
        registry_keys = set(BOOKING_STATE_AUTHORITY.keys())

        phantom = registry_keys - annotations
        assert not phantom, (
            f"Fields in BOOKING_STATE_AUTHORITY but NOT in BookingContext: {phantom}\n"
            "Remove stale entries from agent/booking/state_contract.py"
        )


class TestFieldAuthorityShape:
    """Every registry entry must conform to the FieldAuthority shape."""

    def test_all_entries_have_required_keys(self) -> None:
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY

        required_keys = {"owner_module", "owner_symbol", "readers", "transient", "notes"}
        for field, authority in BOOKING_STATE_AUTHORITY.items():
            missing = required_keys - set(authority.keys())
            assert not missing, f"Registry entry '{field}' is missing keys: {missing}"

    def test_readers_is_list(self) -> None:
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY

        for field, authority in BOOKING_STATE_AUTHORITY.items():
            assert isinstance(
                authority["readers"], list
            ), f"Registry entry '{field}'.readers must be a list"

    def test_transient_is_bool(self) -> None:
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY

        for field, authority in BOOKING_STATE_AUTHORITY.items():
            assert isinstance(
                authority["transient"], bool
            ), f"Registry entry '{field}'.transient must be a bool"


class TestFieldWritersAndReaders:
    """FIELD_WRITERS and FIELD_READERS are derived views of the registry."""

    def test_field_writers_matches_registry_owners(self) -> None:
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY, FIELD_WRITERS

        for field, authority in BOOKING_STATE_AUTHORITY.items():
            assert field in FIELD_WRITERS, f"FIELD_WRITERS missing '{field}'"
            assert (
                FIELD_WRITERS[field] == authority["owner_module"]
            ), f"FIELD_WRITERS['{field}'] != owner_module"

    def test_field_readers_matches_registry_readers(self) -> None:
        from agent.booking.state_contract import BOOKING_STATE_AUTHORITY, FIELD_READERS

        for field, authority in BOOKING_STATE_AUTHORITY.items():
            assert field in FIELD_READERS, f"FIELD_READERS missing '{field}'"
            assert (
                FIELD_READERS[field] == authority["readers"]
            ), f"FIELD_READERS['{field}'] != readers list"


class TestComputeStateForGrounding:
    """AD-4: compute_state_for_grounding rebinds booking_context."""

    def test_rebinds_booking_context(self) -> None:
        from agent.booking.state_contract import compute_state_for_grounding

        state: dict = {"booking_context": {"confirmed": False}, "other": "x"}
        new_ctx: dict = {"confirmed": True, "add_more_asked": True}

        result = compute_state_for_grounding(state, new_ctx)

        assert result["booking_context"] is new_ctx
        assert result["other"] == "x"
        # Original state is not mutated
        assert state["booking_context"] == {"confirmed": False}

    def test_returns_new_dict(self) -> None:
        from agent.booking.state_contract import compute_state_for_grounding

        state: dict = {"booking_context": {}}
        ctx: dict = {"confirmed": True}
        result = compute_state_for_grounding(state, ctx)
        assert result is not state


# ---------------------------------------------------------------------------
# Phase 4 — TypedDict purge
# ---------------------------------------------------------------------------


class TestDeadFieldsPurged:
    """REQ-12: three dead fields must NOT appear in BookingContext after Phase 4."""

    @pytest.mark.parametrize(
        "dead_field",
        [
            "booking_step",
            "available_slots",
            "_disambiguation_questions_shown",
        ],
    )
    def test_dead_field_not_in_annotations(self, dead_field: str) -> None:
        from agent.state.schemas import BookingContext

        annotations = BookingContext.__annotations__
        assert dead_field not in annotations, (
            f"Dead field '{dead_field}' still present in BookingContext. "
            "Remove it per REQ-12 (zero production writers AND readers)."
        )
