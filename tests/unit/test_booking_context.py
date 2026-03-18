from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from agent.tools.availability_tools import check_availability, find_next_available
from agent.tools.info_tools import list_stylists, query_info
from agent.tools.search_services import search_services


def _load_booking_context_module():
    project_root = Path(__file__).resolve().parents[2]
    module_path = project_root / "agent" / "modes" / "booking_context.py"
    spec = importlib.util.spec_from_file_location("agent.modes.booking_context_standalone", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bc_mod = _load_booking_context_module()

ALLOWED_TRANSITIONS = _bc_mod.ALLOWED_TRANSITIONS
BOOKING_FREEZE_ON_ESCALATION = _bc_mod.BOOKING_FREEZE_ON_ESCALATION
BOOKING_PRESERVE_ON_GENERAL = _bc_mod.BOOKING_PRESERVE_ON_GENERAL
BookingDraftContext = _bc_mod.BookingDraftContext
BookingSubstep = _bc_mod.BookingSubstep
STEP_TOOL_REGISTRY = _bc_mod.STEP_TOOL_REGISTRY
normalize_booking_substep = _bc_mod.normalize_booking_substep
validate_booking_context = _bc_mod.validate_booking_context


class TestBookingSubstep:
    def test_enum_has_all_expected_values(self):
        assert [substep.value for substep in BookingSubstep] == [
            "service_selection",
            "add_ons",
            "stylist_selection",
            "slot_selection",
            "customer_name",
            "notes",
            "confirmation",
            "completed",
        ]

    def test_new_substeps_have_expected_values(self):
        assert BookingSubstep.ADD_ONS == "add_ons"
        assert BookingSubstep.CUSTOMER_NAME == "customer_name"

    def test_add_ons_substep_uses_expected_value(self):
        assert BookingSubstep.ADD_ONS == "add_ons"

    def test_customer_name_substep_uses_expected_value(self):
        assert BookingSubstep.CUSTOMER_NAME == "customer_name"

    def test_normalize_booking_substep_supports_new_values(self):
        assert normalize_booking_substep("add_ons") is BookingSubstep.ADD_ONS
        assert normalize_booking_substep("customer_name") is BookingSubstep.CUSTOMER_NAME

    def test_normalize_booking_substep_returns_add_ons(self):
        assert normalize_booking_substep("add_ons") is BookingSubstep.ADD_ONS

    def test_normalize_booking_substep_returns_customer_name(self):
        assert normalize_booking_substep("customer_name") is BookingSubstep.CUSTOMER_NAME

    def test_typed_dict_contains_foundation_fields(self):
        hints = BookingDraftContext.__annotations__

        for field_name in (
            "booking_step",
            "service_id",
            "service_name",
            "selected_services",
            "stylist_id",
            "recurrent_stylist_id",
            "selected_slot",
            "notes",
            "customer_name",
            "pending_clarification",
            "pending_recommendations",
            "availability_time_range",
            "last_intent",
        ):
            assert field_name in hints


class TestAllowedTransitions:
    def test_every_substep_has_transition_entry(self):
        assert set(ALLOWED_TRANSITIONS) == set(BookingSubstep)

    def test_transition_targets_are_valid_substeps(self):
        for transitions in ALLOWED_TRANSITIONS.values():
            for target in transitions:
                assert target in BookingSubstep

    def test_linear_progression_and_backtracking_rules_exist(self):
        assert BookingSubstep.ADD_ONS in ALLOWED_TRANSITIONS[BookingSubstep.SERVICE_SELECTION]
        assert BookingSubstep.SLOT_SELECTION in ALLOWED_TRANSITIONS[BookingSubstep.STYLIST_SELECTION]
        assert BookingSubstep.STYLIST_SELECTION in ALLOWED_TRANSITIONS[BookingSubstep.ADD_ONS]
        assert BookingSubstep.CUSTOMER_NAME in ALLOWED_TRANSITIONS[BookingSubstep.SLOT_SELECTION]
        assert BookingSubstep.NOTES in ALLOWED_TRANSITIONS[BookingSubstep.CUSTOMER_NAME]
        assert BookingSubstep.CONFIRMATION in ALLOWED_TRANSITIONS[BookingSubstep.NOTES]
        assert BookingSubstep.COMPLETED in ALLOWED_TRANSITIONS[BookingSubstep.CONFIRMATION]
        assert BookingSubstep.SERVICE_SELECTION in ALLOWED_TRANSITIONS[BookingSubstep.STYLIST_SELECTION]
        assert BookingSubstep.STYLIST_SELECTION in ALLOWED_TRANSITIONS[BookingSubstep.SLOT_SELECTION]
        assert BookingSubstep.SLOT_SELECTION in ALLOWED_TRANSITIONS[BookingSubstep.CONFIRMATION]
        assert BookingSubstep.SERVICE_SELECTION in ALLOWED_TRANSITIONS[BookingSubstep.CONFIRMATION]

    def test_new_transition_rules_cover_add_ons_and_customer_name(self):
        assert BookingSubstep.STYLIST_SELECTION in ALLOWED_TRANSITIONS[BookingSubstep.ADD_ONS]
        assert BookingSubstep.ADD_ONS in ALLOWED_TRANSITIONS[BookingSubstep.SERVICE_SELECTION]

    def test_add_ons_can_advance_to_stylist_selection(self):
        assert BookingSubstep.STYLIST_SELECTION in ALLOWED_TRANSITIONS[BookingSubstep.ADD_ONS]

    def test_service_selection_can_advance_to_add_ons(self):
        assert BookingSubstep.ADD_ONS in ALLOWED_TRANSITIONS[BookingSubstep.SERVICE_SELECTION]

    def test_completed_is_terminal_state(self):
        assert ALLOWED_TRANSITIONS[BookingSubstep.COMPLETED] == []


class TestContextPreserveRules:
    def test_general_digression_preserves_essential_booking_keys(self):
        for field_name in (
            "booking_step",
            "service_id",
            "service_name",
            "stylist_id",
            "selected_slot",
            "notes",
        ):
            assert field_name in BOOKING_PRESERVE_ON_GENERAL

    def test_escalation_freezes_everything_general_preserves_plus_handoff_flag(self):
        assert BOOKING_PRESERVE_ON_GENERAL.issubset(BOOKING_FREEZE_ON_ESCALATION)
        assert "awaiting_human" in BOOKING_FREEZE_ON_ESCALATION


class TestStepToolRegistry:
    def test_every_substep_has_registry_entry(self):
        assert set(STEP_TOOL_REGISTRY) == set(BookingSubstep)

    def test_registry_points_to_existing_tool_names(self):
        actual_tool_names = {
            query_info.name,
            search_services.name,
            list_stylists.name,
            check_availability.name,
            find_next_available.name,
        }

        for substep, tool_names in STEP_TOOL_REGISTRY.items():
            assert isinstance(tool_names, list), f"{substep.value} must map to a list"
            assert all(isinstance(tool_name, str) for tool_name in tool_names)
            assert set(tool_names).issubset(actual_tool_names)

    def test_registry_has_no_duplicate_tool_names_per_substep(self):
        for substep, tool_names in STEP_TOOL_REGISTRY.items():
            assert len(tool_names) == len(set(tool_names)), f"{substep.value} has duplicate tools"


class TestValidateBookingContext:
    def test_defaults_missing_step_to_service_selection(self):
        validated = validate_booking_context({})

        assert validated["booking_step"] == BookingSubstep.SERVICE_SELECTION.value

    def test_rejects_invalid_substep(self):
        with pytest.raises(ValueError, match="Invalid booking substep"):
            validate_booking_context({"booking_step": "wat"})

    def test_rejects_invalid_transition(self):
        with pytest.raises(ValueError, match="Invalid booking transition"):
            validate_booking_context(
                {
                    "booking_step": BookingSubstep.CONFIRMATION.value,
                    "service_id": "svc-1",
                    "service_name": "Cortar",
                    "stylist_id": "sty-1",
                    "stylist_name": "Maria",
                    "selected_slot": {"start": "2026-03-20T10:00:00+01:00"},
                },
                previous_substep=BookingSubstep.SERVICE_SELECTION,
            )

    @pytest.mark.parametrize(
        ("substep", "context"),
        [
            (
                BookingSubstep.STYLIST_SELECTION,
                {
                    "booking_step": BookingSubstep.STYLIST_SELECTION.value,
                    "service_id": "svc-1",
                    "service_name": "Cortar",
                },
            ),
            (
                BookingSubstep.SLOT_SELECTION,
                {
                    "booking_step": BookingSubstep.SLOT_SELECTION.value,
                    "service_id": "svc-1",
                    "service_name": "Cortar",
                    "stylist_id": "sty-1",
                    "stylist_name": "Maria",
                },
            ),
            (
                BookingSubstep.NOTES,
                {
                    "booking_step": BookingSubstep.NOTES.value,
                    "service_id": "svc-1",
                    "service_name": "Cortar",
                    "stylist_id": "sty-1",
                    "stylist_name": "Maria",
                    "selected_slot": {"start": "2026-03-20T10:00:00+01:00"},
                },
            ),
        ],
    )
    def test_accepts_valid_context_for_substep(self, substep, context):
        validated = validate_booking_context(context)

        assert validated["booking_step"] == substep.value

    @pytest.mark.parametrize(
        ("context", "missing_field"),
        [
            (
                {"booking_step": BookingSubstep.STYLIST_SELECTION.value, "service_name": "Cortar"},
                "service_id",
            ),
            (
                {
                    "booking_step": BookingSubstep.SLOT_SELECTION.value,
                    "service_id": "svc-1",
                    "service_name": "Cortar",
                    "stylist_name": "Maria",
                },
                "stylist_id",
            ),
            (
                {
                    "booking_step": BookingSubstep.CONFIRMATION.value,
                    "service_id": "svc-1",
                    "service_name": "Cortar",
                    "stylist_id": "sty-1",
                    "stylist_name": "Maria",
                },
                "selected_slot",
            ),
        ],
    )
    def test_rejects_missing_required_fields(self, context, missing_field):
        with pytest.raises(ValueError, match=missing_field):
            validate_booking_context(context)
