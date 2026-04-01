"""Unit tests for tool_extractors.py.

Tests all extractor functions with realistic tool response shapes,
verifying that BookingContext is mutated correctly.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode
from agent.modes.tool_extractors import (
    TOOL_EXTRACTORS,
    _apply_resolved_option,
    _previous_assistant_presented_candidates,
    _previous_assistant_presented_clarification,
    _resolve_user_candidate_selection,
    _resolve_user_clarification_selection,
    _safe_parse,
    apply_all_tool_results,
    extract_booking_result,
    extract_customer_fields,
    extract_service_audience_hint,
    extract_service_fields,
    extract_slot_fields,
    extract_stylist_fields,
)


# ============================================================================
# _safe_parse
# ============================================================================


class TestSafeParse:
    def test_parse_dict_passthrough(self):
        d = {"a": 1}
        assert _safe_parse(d) == {"a": 1}

    def test_parse_json_string(self):
        assert _safe_parse('{"a": 1}') == {"a": 1}

    def test_parse_invalid_string(self):
        assert _safe_parse("not json") is None

    def test_parse_int(self):
        assert _safe_parse(42) is None

    def test_parse_none(self):
        assert _safe_parse(None) is None

    def test_parse_json_list_string(self):
        """JSON list string is not a dict — returns None."""
        assert _safe_parse("[1, 2, 3]") is None


# ============================================================================
# extract_service_audience_hint
# ============================================================================


class TestExtractServiceAudienceHint:
    def test_caballero(self):
        assert extract_service_audience_hint("Corte Caballero") == "adult_male"

    def test_dama(self):
        assert extract_service_audience_hint("Corte de Dama") == "adult_female"

    def test_nina(self):
        assert extract_service_audience_hint("Peinado Niña Comunión") == "child_female"

    def test_no_hint(self):
        assert extract_service_audience_hint("Bioterapia Facial") is None

    def test_none_input(self):
        assert extract_service_audience_hint(None) is None

    def test_accent_normalization(self):
        """Accented characters should be normalized before matching."""
        assert extract_service_audience_hint("Corte de Niño") == "child_male"


# ============================================================================
# extract_service_fields — Shape 1 (resolved_service)
# ============================================================================


class TestExtractServiceFieldsShape1:
    def test_resolved_service_populates_all_fields(self):
        ctx = BookingContext()
        result = {
            "resolved_service": {
                "id": "abc-123",
                "name": "Corte de Dama",
                "duration_minutes": 45,
                "category": "HAIRDRESSING",
                "family": "corte",
                "ask_if_missing": [],
                "combo_recommendations": [],
                "description": "Corte para mujer",
            },
            "count": 1,
            "query": "corte dama",
        }
        extract_service_fields(result, ctx)

        assert ctx.service_id == "abc-123"
        assert ctx.service_name == "Corte de Dama"
        assert ctx.service_category == "HAIRDRESSING"
        assert ctx.service_duration_minutes == 45
        assert ctx.service_family == "corte"
        assert ctx.selected_services == ["Corte de Dama"]

    def test_resolved_service_clears_matching_disambiguation(self):
        ctx = BookingContext(
            pending_clarifications=[
                {
                    "axis": "audience",
                    "options": [
                        {"service_name": "Corte de Dama", "service_id": "abc-123"},
                    ],
                }
            ],
            candidate_services=[{"id": "x", "name": "X"}],
        )
        result = {
            "resolved_service": {
                "id": "abc-123",
                "name": "Corte de Dama",
                "duration_minutes": 45,
                "category": "HAIRDRESSING",
            },
            "count": 1,
            "query": "corte dama",
        }
        extract_service_fields(result, ctx)

        assert ctx.pending_clarifications == []
        assert ctx.candidate_services == []

    def test_resolved_service_sets_audience_hint(self):
        ctx = BookingContext()
        result = {
            "resolved_service": {
                "id": "abc-123",
                "name": "Corte Caballero",
                "duration_minutes": 30,
                "category": "HAIRDRESSING",
            },
            "count": 1,
            "query": "corte caballero",
        }
        extract_service_fields(result, ctx)
        assert ctx.service_audience_hint == "adult_male"

    def test_resolved_service_preserves_existing_audience_hint(self):
        ctx = BookingContext(service_audience_hint="child_female")
        result = {
            "resolved_service": {
                "id": "abc-123",
                "name": "Corte de Dama",
                "duration_minutes": 45,
                "category": "HAIRDRESSING",
            },
            "count": 1,
            "query": "corte dama",
        }
        extract_service_fields(result, ctx)
        assert ctx.service_audience_hint == "child_female"

    def test_resolved_service_preserves_addon_services(self):
        ctx = BookingContext(selected_services=["Barba"])
        result = {
            "resolved_service": {
                "id": "abc-123",
                "name": "Corte Caballero",
                "duration_minutes": 30,
                "category": "HAIRDRESSING",
            },
            "count": 1,
            "query": "corte",
        }
        extract_service_fields(result, ctx)
        assert ctx.selected_services == ["Corte Caballero", "Barba"]


# ============================================================================
# extract_service_fields — Shape 2 (clarification_needed)
# ============================================================================


class TestExtractServiceFieldsShape2:
    def test_clarification_sets_pending(self):
        ctx = BookingContext()
        result = {
            "clarification_needed": {
                "axis": "hair_density",
                "question_hint": "¿Es cabello normal o muy largo/denso?",
                "options": [
                    {
                        "label": "Normal",
                        "value": "normal",
                        "service_name": "Mechas",
                        "service_id": "m1",
                        "duration_minutes": 90,
                    },
                    {
                        "label": "Largo/Denso",
                        "value": "largo",
                        "service_name": "Mechas XL",
                        "service_id": "m2",
                        "duration_minutes": 120,
                    },
                ],
            },
            "count": 0,
            "query": "mechas",
        }
        extract_service_fields(result, ctx)

        assert len(ctx.pending_clarifications) == 1
        assert ctx.pending_clarifications[0]["axis"] == "hair_density"
        assert len(ctx.pending_clarifications[0]["options"]) == 2
        assert ctx.service_id is None  # NOT resolved yet

    def test_audience_clarification_auto_resolves_when_hint_matches(self):
        """When selected_services already has a service and a new search returns
        clarification_needed with axis=audience, auto-resolve inline if the
        service_audience_hint matches an option. This prevents same-turn
        clobbering of resolved services."""
        ctx = BookingContext()
        ctx.selected_services = ["Cultura de Color"]
        ctx.service_audience_hint = "dama"
        result = {
            "clarification_needed": {
                "axis": "audience",
                "question_hint": "¿El corte es para caballero, dama, niño, niña o bebé?",
                "options": [
                    {
                        "label": "Caballero",
                        "value": "caballero",
                        "service_name": "Corte Caballero",
                        "service_id": "cc1",
                        "duration_minutes": 30,
                    },
                    {
                        "label": "Dama",
                        "value": "dama",
                        "service_name": "Cortar",
                        "service_id": "cd1",
                        "duration_minutes": 40,
                    },
                ],
            },
        }
        extract_service_fields(result, ctx)

        # Should auto-resolve without appending to pending_clarifications
        assert ctx.pending_clarifications == []
        assert "Cortar" in ctx.selected_services
        assert "Cultura de Color" in ctx.selected_services
        assert len(ctx.selected_services) == 2

    def test_audience_clarification_not_auto_resolved_without_hint(self):
        """Without service_audience_hint, clarification should be set normally."""
        ctx = BookingContext()
        ctx.selected_services = ["Cultura de Color"]
        # No service_audience_hint set
        result = {
            "clarification_needed": {
                "axis": "audience",
                "question_hint": "¿El corte es para caballero o dama?",
                "options": [
                    {
                        "label": "Caballero",
                        "value": "caballero",
                        "service_name": "Corte Caballero",
                        "service_id": "cc1",
                    },
                    {
                        "label": "Dama",
                        "value": "dama",
                        "service_name": "Cortar",
                        "service_id": "cd1",
                    },
                ],
            },
        }
        extract_service_fields(result, ctx)

        assert len(ctx.pending_clarifications) == 1
        assert ctx.pending_clarifications[0]["axis"] == "audience"

    def test_non_audience_clarification_always_sets_pending(self):
        """Non-audience clarification should always set pending, even with services."""
        ctx = BookingContext()
        ctx.selected_services = ["Cultura de Color"]
        ctx.service_audience_hint = "dama"
        result = {
            "clarification_needed": {
                "axis": "hair_density",
                "options": [
                    {
                        "label": "Normal",
                        "value": "normal",
                        "service_name": "Mechas",
                        "service_id": "m1",
                    },
                    {
                        "label": "Largo",
                        "value": "largo",
                        "service_name": "Mechas XL",
                        "service_id": "m2",
                    },
                ],
            },
        }
        extract_service_fields(result, ctx)

        assert len(ctx.pending_clarifications) == 1
        assert ctx.pending_clarifications[0]["axis"] == "hair_density"


# ============================================================================
# extract_service_fields — Shape 3 (services list)
# ============================================================================


class TestExtractServiceFieldsShape3:
    def test_single_candidate_auto_resolves(self):
        ctx = BookingContext()
        result = {
            "services": [
                {
                    "id": "bio-1",
                    "name": "Bioterapia Facial",
                    "duration_minutes": 60,
                    "category": "AESTHETICS",
                    "match_score": 85,
                }
            ],
            "count": 1,
            "query": "bioterapia facial",
        }
        extract_service_fields(result, ctx)

        assert ctx.service_id == "bio-1"
        assert ctx.service_name == "Bioterapia Facial"
        assert ctx.service_category == "AESTHETICS"
        assert ctx.service_duration_minutes == 60
        assert ctx.selected_services == ["Bioterapia Facial"]
        assert ctx.candidate_services == []
        assert ctx.pending_clarifications == []

    def test_multiple_candidates_stored(self):
        ctx = BookingContext()
        result = {
            "services": [
                {
                    "id": "c1",
                    "name": "Corte + Peinado (Largo)",
                    "duration_minutes": 45,
                    "category": "HAIRDRESSING",
                    "match_score": 90,
                },
                {
                    "id": "c2",
                    "name": "Corte + Peinado (Corto)",
                    "duration_minutes": 35,
                    "category": "HAIRDRESSING",
                    "match_score": 85,
                },
            ],
            "count": 2,
            "query": "corte peinado",
        }
        extract_service_fields(result, ctx)

        assert ctx.service_id is None  # Not resolved
        assert ctx.candidate_services == result["services"]
        assert len(ctx.candidate_services) == 2

    def test_empty_services_list(self):
        ctx = BookingContext()
        result = {
            "services": [],
            "count": 0,
            "query": "xyz",
            "message": "No se encontraron servicios",
        }
        extract_service_fields(result, ctx)

        assert ctx.service_id is None
        assert ctx.candidate_services == []


# ============================================================================
# extract_slot_fields
# ============================================================================


class TestExtractSlotFields:
    def test_check_availability_slots_populated(self):
        ctx = BookingContext()
        result = {
            "available_slots": [
                {
                    "time": "10:00",
                    "end_time": "11:30",
                    "stylist": "María",
                    "stylist_id": "s1",
                    "date": "2026-03-27",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                },
                {
                    "time": "14:00",
                    "end_time": "15:30",
                    "stylist": "María",
                    "stylist_id": "s1",
                    "date": "2026-03-27",
                    "full_datetime": "2026-03-27T14:00:00+01:00",
                },
            ],
            "is_same_day": False,
            "holiday_detected": False,
            "date_too_soon": False,
            "error": None,
        }
        extract_slot_fields(result, ctx)

        assert ctx.offered_slots is not None
        assert len(ctx.offered_slots) == 2
        assert ctx.offered_slots[0]["time"] == "10:00"

    def test_selected_slot_not_set(self):
        """Extracting slots must NOT set selected_slot — user must choose."""
        ctx = BookingContext()
        result = {
            "available_slots": [
                {
                    "time": "10:00",
                    "end_time": "11:30",
                    "stylist": "María",
                    "stylist_id": "s1",
                    "date": "2026-03-27",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                }
            ],
            "error": None,
        }
        extract_slot_fields(result, ctx)

        assert ctx.selected_slot is None

    def test_overwrites_existing_slots(self):
        """New behavior: offered_slots is always overwritten with new results."""
        ctx = BookingContext(
            offered_slots=[{"time": "09:00", "stylist": "Ana", "date": "2026-03-26"}]
        )
        new_slots = [{"time": "11:00", "stylist": "María", "date": "2026-03-27"}]
        result = {"available_slots": new_slots, "error": None}
        extract_slot_fields(result, ctx)

        # Always overwrite — old slots replaced with new ones
        assert ctx.offered_slots == new_slots

    def test_find_next_available_legacy_shape(self):
        """find_next_available with available_stylists (legacy format)."""
        ctx = BookingContext()
        result = {
            "available_stylists": [
                {
                    "stylist_name": "María",
                    "stylist_id": "s1",
                    "slots": [
                        {
                            "time": "10:00",
                            "date": "2026-03-27",
                            "day_name": "viernes",
                            "full_datetime": "2026-03-27T10:00:00+01:00",
                            "stylist": "María",
                            "stylist_id": "s1",
                        }
                    ],
                    "slots_shown": 1,
                    "slots_total": 1,
                }
            ],
            "total_slots_found": 1,
            "dates_searched": 3,
            "error": None,
        }
        extract_slot_fields(result, ctx)

        assert ctx.offered_slots is not None
        assert len(ctx.offered_slots) == 1
        assert ctx.offered_slots[0]["stylist"] == "María"

    def test_find_next_available_v42_soonest_any(self):
        """find_next_available v4.2: soonest_any slot is extracted."""
        ctx = BookingContext()
        result = {
            "available_stylists": [],
            "selected_stylist_slots": [
                {
                    "time": "11:00",
                    "date": "2026-03-28",
                    "stylist": "Pilar",
                    "stylist_id": "s2",
                }
            ],
            "soonest_any": {
                "time": "10:00",
                "date": "2026-03-27",
                "stylist_name": "Ana",
                "stylist_id": "s3",
                "is_soonest_any": True,
                "is_different_stylist": True,
            },
            "error": None,
        }
        extract_slot_fields(result, ctx)

        assert ctx.offered_slots is not None
        assert len(ctx.offered_slots) == 1
        assert ctx.offered_slots[0]["stylist"] == "Pilar"
        assert ctx.soonest_any_slot is not None
        assert "Ana" in ctx.soonest_any_slot
        assert "10:00" in ctx.soonest_any_slot

    def test_empty_slots_clears_offered_slots(self):
        """New behavior: empty slots list clears offered_slots."""
        ctx = BookingContext(offered_slots=[{"time": "09:00"}])
        result = {
            "available_slots": [],
            "error": None,
        }
        extract_slot_fields(result, ctx)
        # Empty result clears offered_slots to prevent stale slots
        assert ctx.offered_slots == []

    def test_always_overwrites_regardless_of_refresh_flag(self):
        """No guard: offered_slots are always overwritten, regardless of needs_availability_refresh."""
        stale_slots = [{"time": "09:00", "stylist": "Ana", "date": "2026-03-26"}]
        ctx = BookingContext(
            offered_slots=stale_slots,
            needs_availability_refresh=False,  # Guard would have blocked this, but not anymore
        )
        new_slots = [{"time": "11:00", "stylist": "María", "date": "2026-03-27"}]
        extract_slot_fields({"available_slots": new_slots, "error": None}, ctx)

        # Always overwrite — no guard check
        assert ctx.offered_slots == new_slots
        # Flag is cleared after successful update
        assert ctx.needs_availability_refresh is False

    def test_guard_allows_overwrite_when_no_existing_slots(self):
        """Guard condition: offered_slots=None (even with needs_refresh=False) lets through."""
        ctx = BookingContext(
            offered_slots=None,  # No slots yet — first availability call
            needs_availability_refresh=False,
        )
        new_slots = [{"time": "10:00", "stylist": "María", "date": "2026-03-27"}]
        extract_slot_fields({"available_slots": new_slots, "error": None}, ctx)

        # No slots before → always writes
        assert ctx.offered_slots == new_slots

    def test_extract_slot_fields_overwrites_existing(self):
        """Phase 2.1: New slots unconditionally replace old slots."""
        ctx = BookingContext(offered_slots=[{"time": "09:00", "stylist": "Ana"}])
        new_slots = [
            {"time": "10:00", "stylist": "María"},
            {"time": "10:30", "stylist": "Pilar"},
        ]
        extract_slot_fields({"available_slots": new_slots, "error": None}, ctx)
        assert ctx.offered_slots == new_slots
        assert len(ctx.offered_slots) == 2

    def test_extract_slot_fields_empty_clears(self):
        """Phase 2.2: Empty result clears offered_slots to prevent stale slots."""
        ctx = BookingContext(
            offered_slots=[
                {"time": "09:00", "stylist": "Ana"},
                {"time": "10:00", "stylist": "María"},
            ]
        )
        extract_slot_fields({"available_slots": [], "error": None}, ctx)
        assert ctx.offered_slots == []

    def test_empty_result_produces_empty_offered_slots(self):
        """When availability search returns 0 slots, offered_slots must be cleared."""
        ctx = BookingContext(
            offered_slots=[{"time": "10:00", "date": "2026-03-30", "stylist": "Pilar"}] * 5,
        )

        # Simulate tool result with no available slots
        empty_result = {
            "available_slots": [],
            "total_slots_found": 0,
            "soonest_any": None,
        }
        extract_slot_fields(empty_result, ctx)

        assert ctx.offered_slots == []


# ============================================================================
# extract_stylist_fields
# ============================================================================


class TestExtractStylistFields:
    def test_stylists_populated(self):
        ctx = BookingContext()
        result = {
            "stylists": [
                {"id": "s1", "name": "María", "category": "HAIRDRESSING"},
                {"id": "s2", "name": "Ana", "category": "HAIRDRESSING"},
            ],
            "count": 2,
        }
        extract_stylist_fields(result, ctx)

        assert len(ctx.prefetched_stylists) == 2
        assert ctx.prefetched_stylists[0]["name"] == "María"

    def test_does_not_auto_assign_stylist_id(self):
        """Even with 1 stylist, stylist_id is NOT auto-assigned."""
        ctx = BookingContext()
        result = {
            "stylists": [
                {"id": "s1", "name": "María", "category": "HAIRDRESSING"},
            ],
            "count": 1,
        }
        extract_stylist_fields(result, ctx)

        assert ctx.stylist_id is None
        assert ctx.stylist_name is None
        assert len(ctx.prefetched_stylists) == 1

    def test_empty_stylists(self):
        ctx = BookingContext()
        result = {"stylists": [], "count": 0}
        extract_stylist_fields(result, ctx)

        assert ctx.prefetched_stylists == []


# ============================================================================
# extract_customer_fields
# ============================================================================


class TestExtractCustomerFields:
    def test_get_customer_success(self):
        ctx = BookingContext()
        result = {
            "id": "cust-abc",
            "phone": "+34612345678",
            "first_name": "Pepe",
            "last_name": "García",
            "total_spent": 150.0,
            "created_at": "2025-01-01T00:00:00+01:00",
        }
        extract_customer_fields(result, ctx)

        assert ctx.customer_id == "cust-abc"
        assert ctx.customer_name == "Pepe"

    def test_create_customer_success(self):
        ctx = BookingContext()
        result = {
            "id": "cust-new",
            "phone": "+34612345678",
            "first_name": "Laura",
            "last_name": "",
            "total_spent": 0.0,
            "created_at": "2026-03-23T10:00:00+01:00",
        }
        extract_customer_fields(result, ctx)

        assert ctx.customer_id == "cust-new"
        assert ctx.customer_name == "Laura"

    def test_update_customer_success(self):
        ctx = BookingContext(customer_id="cust-abc", customer_name="Pedro")
        result = {
            "success": True,
            "customer_id": "cust-abc",
            "first_name": "Pepe",
            "last_name": "García",
        }
        extract_customer_fields(result, ctx)

        assert ctx.customer_id == "cust-abc"
        assert ctx.customer_name == "Pepe"

    def test_customer_not_found(self):
        """get with non-existent phone — no fields set, failure counter NOT incremented.

        exists=False is a valid "customer not found" response, not a failure.
        The LLM sees it and calls action='create' next. Incrementing the counter
        here would trip the circuit breaker on the normal get→create sequence for
        new customers.
        """
        ctx = BookingContext()
        result = {
            "exists": False,
            "phone": "+34999999999",
            "message": "Customer not found.",
        }
        extract_customer_fields(result, ctx)

        assert ctx.customer_id is None
        assert ctx.customer_name is None
        assert ctx.manage_customer_failure_count == 0

    def test_only_id_set_when_no_name(self):
        ctx = BookingContext()
        result = {"id": "cust-abc"}
        extract_customer_fields(result, ctx)

        assert ctx.customer_id == "cust-abc"
        assert ctx.customer_name is None


# ============================================================================
# extract_booking_result
# ============================================================================


class TestExtractBookingResult:
    def test_booking_success(self):
        ctx = BookingContext()
        result = {
            "success": True,
            "appointment_id": "apt-123",
            "google_calendar_event_id": "gcal-456",
            "start_time": "2026-03-27T10:00:00+01:00",
            "end_time": "2026-03-27T10:45:00+01:00",
            "total_price": 45.0,
            "duration_minutes": 45,
            "customer_id": "cust-abc",
            "stylist_id": "s1",
            "service_ids": ["svc-1"],
        }
        extract_booking_result(result, ctx)

        assert ctx._booking_completed is True

    def test_booking_failure(self):
        ctx = BookingContext()
        result = {
            "success": False,
            "error_code": "SLOT_TAKEN",
            "error_message": "El horario ya no está disponible.",
            "details": {},
        }
        extract_booking_result(result, ctx)

        assert ctx._booking_completed is False

    def test_booking_ambiguous_service_failure(self):
        ctx = BookingContext()
        result = {
            "success": False,
            "error_code": "AMBIGUOUS_SERVICE",
            "error_message": "El servicio es ambiguo.",
            "details": {"query": "corte", "options": []},
        }
        extract_booking_result(result, ctx)

        assert ctx._booking_completed is False


# ============================================================================
# apply_all_tool_results — dispatcher
# ============================================================================


class TestApplyAllToolResults:
    def test_empty_results(self):
        ctx = BookingContext()
        apply_all_tool_results({}, ctx)
        assert ctx.service_id is None
        assert ctx.customer_id is None

    def test_unknown_tool_ignored(self):
        ctx = BookingContext()
        apply_all_tool_results({"query_info": {"some": "data"}}, ctx)
        assert ctx.service_id is None  # No crash, no mutation

    def test_single_tool_routed(self):
        ctx = BookingContext()
        result = {
            "search_services": {
                "resolved_service": {
                    "id": "abc-123",
                    "name": "Corte de Dama",
                    "duration_minutes": 45,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "corte dama",
            }
        }
        apply_all_tool_results(result, ctx)

        assert ctx.service_id == "abc-123"
        assert ctx.service_name == "Corte de Dama"

    def test_multiple_tools_in_one_turn(self):
        ctx = BookingContext()
        results = {
            "search_services": {
                "resolved_service": {
                    "id": "abc-123",
                    "name": "Corte de Dama",
                    "duration_minutes": 45,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "corte dama",
            },
            "check_availability": {
                "available_slots": [
                    {
                        "time": "10:00",
                        "end_time": "10:45",
                        "stylist": "María",
                        "stylist_id": "s1",
                        "date": "2026-03-27",
                        "full_datetime": "2026-03-27T10:00:00+01:00",
                    }
                ],
                "error": None,
            },
        }
        apply_all_tool_results(results, ctx)

        assert ctx.service_id == "abc-123"
        assert ctx.offered_slots is not None
        assert len(ctx.offered_slots) == 1

    def test_json_string_result_parsed(self):
        ctx = BookingContext()
        result_json = json.dumps(
            {
                "stylists": [
                    {"id": "s1", "name": "María", "category": "HAIRDRESSING"},
                ],
                "count": 1,
            }
        )
        apply_all_tool_results({"list_stylists": result_json}, ctx)

        assert len(ctx.prefetched_stylists) == 1

    def test_unparseable_result_skipped(self):
        ctx = BookingContext()
        apply_all_tool_results({"search_services": "not json at all"}, ctx)
        assert ctx.service_id is None  # No crash

    def test_tool_extractors_registry_complete(self):
        """Verify TOOL_EXTRACTORS has all expected tool names."""
        expected = {
            "search_services",
            "check_availability",
            "find_next_available",
            "list_stylists",
            "manage_customer",
            "book",
            "query_info",  # GAP-03: no-op extractor prevents log noise for informational tool
        }
        assert expected == set(TOOL_EXTRACTORS.keys())


# ============================================================================
# extract_booking_result — SLOT_TAKEN cleanup (Phase 2)
# ============================================================================


class TestExtractBookingResultSlotTaken:
    """Test SLOT_TAKEN-specific cleanup in extract_booking_result."""

    def test_slot_taken_clears_offered_slots(self):
        """SLOT_TAKEN error should clear offered_slots to force refresh."""
        ctx = BookingContext(
            offered_slots=[
                {"stylist_id": "s1", "time": "10:00", "full_datetime": "2026-03-24T10:00:00"},
                {"stylist_id": "s1", "time": "11:00", "full_datetime": "2026-03-24T11:00:00"},
            ],
            selected_slot={"stylist_id": "s1", "start_time": "2026-03-24T10:00:00"},
            book_failure_count=0,
        )
        extract_booking_result(
            {"success": False, "error_code": "SLOT_TAKEN", "message": "Slot already booked"},
            ctx,
        )

        assert ctx.offered_slots is None
        assert ctx.selected_slot is None
        assert ctx.book_failure_count == 1

    def test_non_slot_taken_preserves_offered_slots(self):
        """Other errors should NOT clear offered_slots."""
        ctx = BookingContext(
            offered_slots=[{"stylist_id": "s1", "time": "10:00"}],
            book_failure_count=0,
        )
        extract_booking_result(
            {"success": False, "error_code": "VALIDATION_ERROR", "message": "Missing field"},
            ctx,
        )

        assert ctx.offered_slots is not None
        assert len(ctx.offered_slots) == 1
        assert ctx.book_failure_count == 1

    def test_slot_taken_no_prior_slots(self):
        """SLOT_TAKEN with no prior offered_slots — no crash."""
        ctx = BookingContext(offered_slots=None, book_failure_count=0)
        extract_booking_result(
            {"success": False, "error_code": "SLOT_TAKEN"},
            ctx,
        )

        assert ctx.offered_slots is None
        assert ctx.book_failure_count == 1


# ============================================================================
# extract_service_fields Shape 3 — multi-service append (Phase 3)
# ============================================================================


class TestExtractServiceFieldsShape3Append:
    """Test Shape 3 single-match APPEND behavior (Phase 3 fix)."""

    def test_shape3_single_appends_not_overwrites(self):
        """Single Shape 3 result should append to existing selected_services."""
        ctx = BookingContext(
            service_id="uuid-tinte",
            service_name="Tinte Mujer",
            selected_services=["Tinte Mujer"],
        )
        extract_service_fields(
            {"services": [{"id": "uuid-corte", "name": "Corte Mujer", "category": "corte"}]},
            ctx,
        )

        assert ctx.selected_services == ["Corte Mujer", "Tinte Mujer"]
        assert ctx.service_id == "uuid-corte"
        assert ctx.service_name == "Corte Mujer"

    def test_shape3_single_no_duplicate(self):
        """If service already in list, don't duplicate."""
        ctx = BookingContext(
            service_id="uuid-corte",
            service_name="Corte Mujer",
            selected_services=["Corte Mujer"],
        )
        extract_service_fields(
            {"services": [{"id": "uuid-corte", "name": "Corte Mujer", "category": "corte"}]},
            ctx,
        )

        assert ctx.selected_services == ["Corte Mujer"]

    def test_shape3_first_service_empty_list(self):
        """First service via Shape 3 on empty list."""
        ctx = BookingContext(selected_services=[])
        extract_service_fields(
            {"services": [{"id": "uuid-1", "name": "Corte Mujer", "category": "corte"}]},
            ctx,
        )

        assert ctx.selected_services == ["Corte Mujer"]
        assert ctx.service_id == "uuid-1"
        assert ctx.service_name == "Corte Mujer"


# ============================================================================
# extract_service_fields — combo recommendations (Phase 4)
# ============================================================================


class TestExtractComboRecommendations:
    """Test combo_recommendations extraction from Shape 1 resolved_service."""

    def test_shape1_extracts_combo_recommendations(self):
        """Shape 1 with combo_recommendations populates pending_recommendations."""
        ctx = BookingContext()
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-tinte",
                    "name": "Tinte",
                    "duration_minutes": 90,
                    "category": "HAIRDRESSING",
                    "combo_recommendations": ["Hidratación", "Corte de Señora"],
                },
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )

        assert ctx.pending_recommendations == ["Hidratación", "Corte de Señora"]
        assert ctx.recommendations_shown is False

    def test_does_not_overwrite_existing_recommendations(self):
        """If pending_recommendations already set, don't overwrite."""
        ctx = BookingContext(pending_recommendations=["Existing Recommendation"])
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-tinte",
                    "name": "Tinte",
                    "duration_minutes": 90,
                    "category": "HAIRDRESSING",
                    "combo_recommendations": ["New Recommendation"],
                },
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )

        assert ctx.pending_recommendations == ["Existing Recommendation"]

    def test_empty_combo_recommendations_ignored(self):
        """Empty combo_recommendations list does not populate pending."""
        ctx = BookingContext()
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-corte",
                    "name": "Corte de Dama",
                    "duration_minutes": 45,
                    "category": "HAIRDRESSING",
                    "combo_recommendations": [],
                },
                "count": 1,
                "query": "corte dama",
            },
            ctx,
        )

        assert ctx.pending_recommendations == []

    def test_no_combo_recommendations_key(self):
        """Missing combo_recommendations key does not crash."""
        ctx = BookingContext()
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-corte",
                    "name": "Corte de Dama",
                    "duration_minutes": 45,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "corte dama",
            },
            ctx,
        )

        assert ctx.pending_recommendations == []


# ============================================================================
# services_locked guard (booking-retry-resilience Phase 2)
# ============================================================================


class TestServicesLocked:
    """Test services_locked lifecycle: default, lock trigger, guard, serialization."""

    def test_services_locked_false_by_default(self):
        """New BookingContext defaults to services_locked=False."""
        ctx = BookingContext()
        assert ctx.services_locked is False

    def test_apply_all_does_not_lock_without_offered_slots(self):
        """apply_all_tool_results does NOT lock when offered_slots is absent."""
        ctx = BookingContext()
        apply_all_tool_results(
            {
                "search_services": {
                    "resolved_service": {
                        "id": "uuid-corte",
                        "name": "Corte Caballero",
                        "duration_minutes": 30,
                        "category": "HAIRDRESSING",
                    },
                    "count": 1,
                    "query": "corte caballero",
                },
            },
            ctx,
        )

        assert ctx.services_locked is False  # No offered_slots → not locked
        assert ctx.selected_services == ["Corte Caballero"]
        assert ctx.service_id == "uuid-corte"

    def test_apply_all_does_not_lock_even_with_offered_slots(self):
        """apply_all_tool_results no longer locks — lock moved to book()."""
        ctx = BookingContext(
            offered_slots=[{"time": "10:00", "stylist_id": "s1"}],
        )
        apply_all_tool_results(
            {
                "search_services": {
                    "resolved_service": {
                        "id": "uuid-corte",
                        "name": "Corte Caballero",
                        "duration_minutes": 30,
                        "category": "HAIRDRESSING",
                    },
                    "count": 1,
                    "query": "corte caballero",
                },
            },
            ctx,
        )

        assert ctx.services_locked is False  # Lock moved to book()
        assert ctx.selected_services == ["Corte Caballero"]

    def test_extract_service_fields_appends_when_locked(self):
        """When services_locked=True, scalars are protected but selected_services appends."""
        ctx = BookingContext(
            services_locked=True,
            service_id="uuid-corte",
            service_name="Corte Caballero",
            selected_services=["Corte Caballero", "Barba"],
        )
        # Try to overwrite with a different service
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-tinte",
                    "name": "Tinte",
                    "duration_minutes": 90,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )

        # Scalars protected — NOT overwritten
        assert ctx.service_id == "uuid-corte"
        assert ctx.service_name == "Corte Caballero"
        # But Tinte was appended
        assert ctx.selected_services == ["Corte Caballero", "Barba", "Tinte"]

    def test_two_services_same_turn_both_resolve(self):
        """Two search_services in same turn: both resolve before lock engages."""
        ctx = BookingContext()
        apply_all_tool_results(
            {
                "search_services": [
                    {
                        "resolved_service": {
                            "id": "uuid-corte",
                            "name": "Corte Caballero",
                            "duration_minutes": 30,
                            "category": "HAIRDRESSING",
                        },
                        "count": 1,
                        "query": "corte caballero",
                    },
                    {
                        "resolved_service": {
                            "id": "uuid-barba",
                            "name": "Barba",
                            "duration_minutes": 20,
                            "category": "HAIRDRESSING",
                        },
                        "count": 1,
                        "query": "barba",
                    },
                ],
            },
            ctx,
        )

        # Both services resolved
        assert "Corte Caballero" in ctx.selected_services
        assert "Barba" in ctx.selected_services
        # Lock does NOT engage without offered_slots
        assert ctx.services_locked is False

    def test_slot_taken_retry_preserves_services(self):
        """After SLOT_TAKEN retry, re-calling search_services does NOT drop add-ons.

        With partial lock: scalars are protected, and "Corte Caballero" is already
        in selected_services so the dedup guard prevents duplicate append.
        """
        ctx = BookingContext(
            services_locked=True,
            service_id="uuid-corte",
            service_name="Corte Caballero",
            selected_services=["Corte Caballero", "Barba"],
        )
        # Retry: LLM re-calls search_services for only the primary service
        apply_all_tool_results(
            {
                "search_services": {
                    "resolved_service": {
                        "id": "uuid-corte",
                        "name": "Corte Caballero",
                        "duration_minutes": 30,
                        "category": "HAIRDRESSING",
                    },
                    "count": 1,
                    "query": "corte caballero",
                },
            },
            ctx,
        )

        # Both services preserved — Barba NOT dropped, no duplicate Corte
        assert ctx.selected_services == ["Corte Caballero", "Barba"]
        assert ctx.services_locked is True

    def test_services_locked_reset_on_new_context(self):
        """New BookingContext always starts with services_locked=False."""
        ctx = BookingContext()
        assert ctx.services_locked is False

    def test_services_locked_survives_serialization(self):
        """services_locked=True persists through to_mode_context/from_mode_context."""
        ctx = BookingContext(
            services_locked=True,
            service_id="uuid-corte",
            service_name="Corte Caballero",
            selected_services=["Corte Caballero"],
        )
        serialized = ctx.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

        assert restored.services_locked is True
        assert restored.selected_services == ["Corte Caballero"]

    def test_addon_service_resolves_before_slots_offered(self):
        """Add-on service on a subsequent turn resolves when no offered_slots yet."""
        ctx = BookingContext(
            service_id="uuid-corte",
            service_name="Corte Caballero",
            selected_services=["Corte Caballero"],
            services_locked=False,  # No offered_slots → not locked
        )
        # User says "y también barba" on a subsequent turn
        apply_all_tool_results(
            {
                "search_services": {
                    "resolved_service": {
                        "id": "uuid-barba",
                        "name": "Barba",
                        "duration_minutes": 20,
                        "category": "HAIRDRESSING",
                    },
                    "count": 1,
                    "query": "barba",
                },
            },
            ctx,
        )

        # Add-on resolves because services_locked is still False
        assert "Barba" in ctx.selected_services
        assert "Corte Caballero" in ctx.selected_services
        # Still not locked (no offered_slots)
        assert ctx.services_locked is False

    def test_services_not_locked_on_slots_offered_same_turn(self):
        """Lock no longer engages from apply_all — only from book()."""
        ctx = BookingContext()
        apply_all_tool_results(
            {
                "search_services": {
                    "resolved_service": {
                        "id": "uuid-corte",
                        "name": "Corte Caballero",
                        "duration_minutes": 30,
                        "category": "HAIRDRESSING",
                    },
                    "count": 1,
                    "query": "corte caballero",
                },
                "check_availability": {
                    "available_slots": [
                        {
                            "time": "10:00",
                            "stylist_id": "s1",
                            "date": "2026-03-27",
                            "full_datetime": "2026-03-27T10:00:00+01:00",
                        }
                    ],
                    "error": None,
                },
            },
            ctx,
        )

        # Lock no longer triggers from apply_all — moved to book()
        assert ctx.services_locked is False
        assert ctx.selected_services == ["Corte Caballero"]
        assert ctx.offered_slots is not None


# ============================================================================
# Multi-service booking fix (SC-1 through SC-5)
# ============================================================================


class TestMultiServiceBookingFix:
    """Tests for multi-service booking fix: partial lock + deferred lock trigger."""

    def test_cross_turn_multi_service_appends(self):
        """SC-1: Cross-turn multi-service — second service appends after slots offered."""
        ctx = BookingContext(
            service_id="uuid-corte",
            service_name="Corte de Señora",
            selected_services=["Corte de Señora"],
            services_locked=False,
            offered_slots=[
                {
                    "time": "10:00",
                    "stylist_id": "s1",
                    "date": "2026-03-27",
                    "full_datetime": "2026-03-27T10:00:00+01:00",
                }
            ],
        )
        # User says "y también tinte" — LLM calls search_services("tinte")
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-tinte",
                    "name": "Tinte",
                    "duration_minutes": 90,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )

        # Both services present; services_locked remains False (no book() yet)
        assert "Corte de Señora" in ctx.selected_services
        assert "Tinte" in ctx.selected_services
        assert ctx.services_locked is False

    def test_locked_appends_without_scalar_overwrite(self):
        """SC-3: Locked context appends new service without overwriting scalars."""
        ctx = BookingContext(
            services_locked=True,
            service_id="uuid-corte",
            service_name="Corte de Señora",
            service_category="HAIRDRESSING",
            service_duration_minutes=45,
            selected_services=["Corte de Señora"],
        )
        # LLM calls search_services("tinte") after a failed book()
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-tinte",
                    "name": "Tinte",
                    "duration_minutes": 90,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )

        # Scalars unchanged
        assert ctx.service_id == "uuid-corte"
        assert ctx.service_name == "Corte de Señora"
        assert ctx.service_category == "HAIRDRESSING"
        assert ctx.service_duration_minutes == 45
        # But Tinte was appended
        assert ctx.selected_services == ["Corte de Señora", "Tinte"]

    def test_locked_shape3_single_appends(self):
        """SC-3 variant: Shape 3 single result also appends when locked."""
        ctx = BookingContext(
            services_locked=True,
            service_id="uuid-corte",
            service_name="Corte de Señora",
            selected_services=["Corte de Señora"],
        )
        extract_service_fields(
            {
                "services": [{"id": "uuid-tinte", "name": "Tinte", "category": "HAIRDRESSING"}],
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )

        assert ctx.service_id == "uuid-corte"  # Scalar protected
        assert ctx.selected_services == ["Corte de Señora", "Tinte"]

    def test_locked_dedup_prevents_duplicate(self):
        """When locked, duplicate service names are NOT appended."""
        ctx = BookingContext(
            services_locked=True,
            service_id="uuid-corte",
            service_name="Corte de Señora",
            selected_services=["Corte de Señora", "Tinte"],
        )
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-tinte",
                    "name": "Tinte",
                    "duration_minutes": 90,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )

        # No duplicate
        assert ctx.selected_services == ["Corte de Señora", "Tinte"]

    def test_no_lock_on_slot_offering(self):
        """SC-4: Lock does NOT engage when slots are offered (only on book())."""
        ctx = BookingContext(
            selected_services=["Corte de Señora"],
            services_locked=False,
        )
        apply_all_tool_results(
            {
                "check_availability": {
                    "available_slots": [
                        {
                            "time": "10:00",
                            "stylist_id": "s1",
                            "date": "2026-03-27",
                            "full_datetime": "2026-03-27T10:00:00+01:00",
                        }
                    ],
                    "error": None,
                },
            },
            ctx,
        )

        assert ctx.services_locked is False
        assert ctx.offered_slots is not None

    def test_lock_on_book_failure(self):
        """SC-5: Lock engages on book() failure (e.g. SLOT_TAKEN)."""
        ctx = BookingContext(
            services_locked=False,
            selected_services=["Corte de Señora", "Tinte"],
        )
        extract_booking_result(
            {"success": False, "error_code": "SLOT_TAKEN", "message": "Slot taken"},
            ctx,
        )

        assert ctx.services_locked is True

    def test_lock_on_book_success(self):
        """On book() success, lock is set briefly then cleared by reset_transient()."""
        ctx = BookingContext(
            services_locked=False,
            selected_services=["Corte de Señora"],
        )
        extract_booking_result(
            {
                "success": True,
                "appointment_id": "apt-123",
                "stylist_id": "s1",
            },
            ctx,
        )

        # reset_transient() is called after success, which clears services_locked
        # so the next booking starts clean
        assert ctx.services_locked is False
        assert ctx._booking_completed is True

    def test_lock_idempotent_on_second_book(self):
        """Second book() call does not crash — lock already True."""
        ctx = BookingContext(
            services_locked=True,
            selected_services=["Corte de Señora"],
        )
        extract_booking_result(
            {"success": False, "error_code": "SLOT_TAKEN"},
            ctx,
        )

        assert ctx.services_locked is True
        assert ctx.book_failure_count == 1


# ============================================================================
# SLOT_TAKEN refresh flag (booking-state-integrity REQ-BSI-2)
# ============================================================================


class TestSlotTakenRefreshFlag:
    """REQ-BSI-2: needs_availability_refresh set/cleared on SLOT_TAKEN and fresh availability."""

    def test_slot_taken_sets_refresh_flag(self):
        """Scenario 1: SLOT_TAKEN sets needs_availability_refresh=True."""
        ctx = BookingContext(
            offered_slots=[
                {"stylist_id": "s1", "time": "10:00", "full_datetime": "2026-03-24T10:00:00"}
            ],
            selected_slot={"stylist_id": "s1", "start_time": "2026-03-24T10:00:00"},
            needs_availability_refresh=False,
        )
        extract_booking_result(
            {"success": False, "error_code": "SLOT_TAKEN", "message": "Slot already booked"},
            ctx,
        )

        assert ctx.needs_availability_refresh is True
        assert ctx.offered_slots is None
        assert ctx.selected_slot is None

    def test_non_slot_taken_does_not_set_refresh_flag(self):
        """Other error codes do NOT set needs_availability_refresh."""
        ctx = BookingContext(
            offered_slots=[{"stylist_id": "s1", "time": "10:00"}],
            needs_availability_refresh=False,
        )
        extract_booking_result(
            {"success": False, "error_code": "VALIDATION_ERROR", "message": "Bad data"},
            ctx,
        )

        assert ctx.needs_availability_refresh is False

    def test_fresh_availability_clears_refresh_flag(self):
        """Scenario 2: extract_slot_fields clears needs_availability_refresh on fresh slots."""
        ctx = BookingContext(
            needs_availability_refresh=True,
            offered_slots=None,
        )
        extract_slot_fields(
            {
                "available_slots": [
                    {
                        "time": "11:00",
                        "end_time": "12:00",
                        "stylist": "Maria",
                        "stylist_id": "s1",
                        "date": "2026-03-27",
                        "full_datetime": "2026-03-27T11:00:00+01:00",
                    }
                ],
                "error": None,
            },
            ctx,
        )

        assert ctx.needs_availability_refresh is False
        assert ctx.offered_slots is not None
        assert len(ctx.offered_slots) == 1

    def test_refresh_flag_default_is_false(self):
        """New BookingContext defaults needs_availability_refresh=False."""
        ctx = BookingContext()
        assert ctx.needs_availability_refresh is False

    def test_booking_success_does_not_set_refresh_flag(self):
        """Successful booking does NOT set the refresh flag."""
        ctx = BookingContext(
            needs_availability_refresh=False,
            offered_slots=[{"stylist_id": "s1", "time": "10:00"}],
        )
        extract_booking_result(
            {
                "success": True,
                "appointment_id": "apt-123",
                "stylist_id": "s1",
            },
            ctx,
        )

        assert ctx.needs_availability_refresh is False
        assert ctx._booking_completed is True

    def test_refresh_flag_survives_serialization(self):
        """needs_availability_refresh=True persists through to_mode_context/from_mode_context."""
        ctx = BookingContext(needs_availability_refresh=True, book_failure_count=1)
        serialized = ctx.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

        assert restored.needs_availability_refresh is True
        assert restored.book_failure_count == 1


# ============================================================================
# extract_booking_result — Rejected results (REQ-BRF-2)
# ============================================================================


class TestExtractBookingResultRejected:
    """REQ-BRF-2: Rejected book() results cause no side effects."""

    def test_rejected_result_no_failure_count_increment(self):
        """Rejected result should NOT increment book_failure_count."""
        ctx = BookingContext(book_failure_count=0)
        extract_booking_result(
            {"rejected": True, "error_code": "NO_OFFERED_SLOTS", "tool_name": "book"},
            ctx,
        )

        assert ctx.book_failure_count == 0

    def test_rejected_result_no_services_locked(self):
        """Rejected result should NOT set services_locked."""
        ctx = BookingContext(services_locked=False)
        extract_booking_result(
            {"rejected": True, "error_code": "NO_CUSTOMER_NAME", "tool_name": "book"},
            ctx,
        )

        assert ctx.services_locked is False

    def test_rejected_result_no_booking_completed(self):
        """Rejected result should NOT set _booking_completed."""
        ctx = BookingContext()
        extract_booking_result(
            {"rejected": True, "error_code": "NEEDS_AVAILABILITY_REFRESH", "tool_name": "book"},
            ctx,
        )

        assert ctx._booking_completed is False

    def test_rejected_result_preserves_needs_availability_refresh(self):
        """Rejected result should NOT change needs_availability_refresh."""
        ctx = BookingContext(needs_availability_refresh=True)
        extract_booking_result(
            {"rejected": True, "error_code": "NEEDS_AVAILABILITY_REFRESH", "tool_name": "book"},
            ctx,
        )

        assert ctx.needs_availability_refresh is True

    def test_real_failure_still_increments(self):
        """Non-rejected failure should still increment book_failure_count."""
        ctx = BookingContext(book_failure_count=0)
        extract_booking_result(
            {"success": False, "error_code": "VALIDATION_ERROR"},
            ctx,
        )

        assert ctx.book_failure_count == 1
        assert ctx.services_locked is True


# ============================================================================
# Clarification queue — Shape 1 + Shape 2 interleaving (REQ-BRF-4, REQ-BRF-5)
# ============================================================================


class TestClarificationQueueBehavior:
    """REQ-BRF-4/5: pending_clarifications is a queue, not a scalar."""

    def test_shape2_appends_to_queue(self):
        """Two Shape 2 results should produce 2 entries in the queue."""
        ctx = BookingContext()
        # First clarification
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "audience",
                    "options": [
                        {
                            "label": "Caballero",
                            "value": "caballero",
                            "service_name": "Corte Caballero",
                            "service_id": "cc1",
                        },
                        {
                            "label": "Dama",
                            "value": "dama",
                            "service_name": "Cortar",
                            "service_id": "cd1",
                        },
                    ],
                },
            },
            ctx,
        )
        assert len(ctx.pending_clarifications) == 1

        # Second clarification (different axis)
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "hair_density",
                    "options": [
                        {
                            "label": "Normal",
                            "value": "normal",
                            "service_name": "Mechas",
                            "service_id": "m1",
                        },
                        {
                            "label": "Largo",
                            "value": "largo",
                            "service_name": "Mechas XL",
                            "service_id": "m2",
                        },
                    ],
                },
            },
            ctx,
        )
        assert len(ctx.pending_clarifications) == 2
        assert ctx.pending_clarifications[0]["axis"] == "audience"
        assert ctx.pending_clarifications[1]["axis"] == "hair_density"

    def test_shape1_then_shape2_preserves_both(self):
        """REQ-BRF-4: Shape 1 (tinte) then Shape 2 (corte clarification).
        selected_services has tinte, pending_clarifications has corte entry."""
        ctx = BookingContext()
        # Shape 1: resolved tinte
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-tinte",
                    "name": "Tinte Completo",
                    "duration_minutes": 90,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )
        assert ctx.selected_services == ["Tinte Completo"]

        # Shape 2: clarification for corte
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "audience",
                    "options": [
                        {
                            "label": "Caballero",
                            "value": "caballero",
                            "service_name": "Corte Caballero",
                            "service_id": "cc1",
                        },
                        {
                            "label": "Dama",
                            "value": "dama",
                            "service_name": "Cortar",
                            "service_id": "cd1",
                        },
                    ],
                },
            },
            ctx,
        )
        assert ctx.selected_services == ["Tinte Completo"]
        assert len(ctx.pending_clarifications) == 1
        assert ctx.pending_clarifications[0]["axis"] == "audience"

    def test_shape2_then_shape1_preserves_both(self):
        """REQ-BRF-4: Reversed order — Shape 2 (corte clarification) then Shape 1 (tinte).
        selected_services has tinte, pending_clarifications still has corte entry."""
        ctx = BookingContext()
        # Shape 2: clarification for corte
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "audience",
                    "options": [
                        {
                            "label": "Caballero",
                            "value": "caballero",
                            "service_name": "Corte Caballero",
                            "service_id": "cc1",
                        },
                        {
                            "label": "Dama",
                            "value": "dama",
                            "service_name": "Cortar",
                            "service_id": "cd1",
                        },
                    ],
                },
            },
            ctx,
        )
        assert len(ctx.pending_clarifications) == 1

        # Shape 1: resolved tinte (unrelated to the pending corte clarification)
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "uuid-tinte",
                    "name": "Tinte Completo",
                    "duration_minutes": 90,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "tinte",
            },
            ctx,
        )
        assert ctx.selected_services == ["Tinte Completo"]
        # Tinte does NOT match any option in the corte clarification, so it stays
        assert len(ctx.pending_clarifications) == 1

    def test_shape1_clears_only_matching_clarification(self):
        """REQ-BRF-5: Shape 1 resolving 'Corte Caballero' removes only the matching
        clarification entry, not unrelated ones."""
        ctx = BookingContext(
            pending_clarifications=[
                {
                    "axis": "audience",
                    "options": [
                        {
                            "label": "Caballero",
                            "value": "caballero",
                            "service_name": "Corte Caballero",
                            "service_id": "cc1",
                        },
                        {
                            "label": "Dama",
                            "value": "dama",
                            "service_name": "Cortar",
                            "service_id": "cd1",
                        },
                    ],
                },
                {
                    "axis": "hair_density",
                    "options": [
                        {
                            "label": "Normal",
                            "value": "normal",
                            "service_name": "Mechas",
                            "service_id": "m1",
                        },
                    ],
                },
            ],
        )
        # Resolve Corte Caballero — should remove the audience entry but keep hair_density
        extract_service_fields(
            {
                "resolved_service": {
                    "id": "cc1",
                    "name": "Corte Caballero",
                    "duration_minutes": 30,
                    "category": "HAIRDRESSING",
                },
                "count": 1,
                "query": "corte caballero",
            },
            ctx,
        )

        assert ctx.selected_services == ["Corte Caballero"]
        assert len(ctx.pending_clarifications) == 1
        assert ctx.pending_clarifications[0]["axis"] == "hair_density"


# ============================================================================
# extract_booking_result — reset_transient integration (Task 4.2)
# ============================================================================


class TestExtractBookingResultResetTransient:
    """Task 4.2: reset_transient() is called on success but NOT on failure."""

    def _populated_ctx(self) -> BookingContext:
        """Return a context with transient fields populated (typical post-booking state)."""
        return BookingContext(
            service_id="svc-001",
            service_name="Corte de Dama",
            stylist_id="sty-001",
            stylist_name="María",
            customer_name="Pepe",
            customer_id="cust-001",
            selected_slot={"start_time": "2026-03-25T10:00:00+01:00"},
            offered_slots=[{"time": "10:00", "stylist": "María"}],
            # Transient fields that reset_transient() should clear
            selected_services=["Corte de Dama", "Tinte"],
            service_audience_hint="adult_female",
            notes="Sin alergia",
            prefetched_stylists=[{"name": "María"}],
            soonest_any_slot="Lunes 25 a las 10:00 con María",
            recurrent_stylist_hint="María",
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=False,
            book_failure_count=0,
            needs_availability_refresh=False,
            services_locked=True,
        )

    # ── Success path: reset_transient() IS called ─────────────────────

    def test_success_clears_selected_services(self):
        """On success, selected_services is cleared by reset_transient()."""
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.selected_services == []

    def test_success_clears_service_audience_hint(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.service_audience_hint is None

    def test_success_clears_notes(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.notes is None

    def test_success_clears_prefetched_stylists(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.prefetched_stylists == []

    def test_success_clears_soonest_any_slot(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.soonest_any_slot is None

    def test_success_clears_pending_recommendations(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.pending_recommendations == []

    def test_success_resets_recommendations_shown(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.recommendations_shown is False

    def test_success_resets_services_locked(self):
        """reset_transient() clears services_locked — follow-up booking starts clean."""
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.services_locked is False

    def test_success_resets_book_failure_count(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.book_failure_count == 0

    def test_success_sets_booking_completed(self):
        """_booking_completed flag is set before reset_transient()."""
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx._booking_completed is True

    def test_success_preserves_customer_name(self):
        """Identity fields are NOT cleared by reset_transient()."""
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.customer_name == "Pepe"

    def test_success_preserves_customer_id(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.customer_id == "cust-001"

    def test_success_preserves_stylist_name(self):
        ctx = self._populated_ctx()
        extract_booking_result({"success": True, "appointment_id": "apt-1"}, ctx)
        assert ctx.stylist_name == "María"

    def test_success_preserves_stylist_id(self):
        ctx = self._populated_ctx()
        extract_booking_result(
            {"success": True, "appointment_id": "apt-1", "stylist_id": "sty-001"},
            ctx,
        )
        assert ctx.stylist_id == "sty-001"

    # ── Failure path: reset_transient() is NOT called ─────────────────

    def test_failure_preserves_selected_services(self):
        """On failure, selected_services is NOT cleared."""
        ctx = self._populated_ctx()
        extract_booking_result(
            {"success": False, "error_code": "VALIDATION_ERROR", "message": "Missing field"},
            ctx,
        )
        assert ctx.selected_services == ["Corte de Dama", "Tinte"]

    def test_failure_preserves_service_audience_hint(self):
        ctx = self._populated_ctx()
        extract_booking_result(
            {"success": False, "error_code": "VALIDATION_ERROR"},
            ctx,
        )
        assert ctx.service_audience_hint == "adult_female"

    def test_failure_preserves_notes(self):
        ctx = self._populated_ctx()
        extract_booking_result(
            {"success": False, "error_code": "VALIDATION_ERROR"},
            ctx,
        )
        assert ctx.notes == "Sin alergia"

    def test_failure_preserves_pending_recommendations(self):
        ctx = self._populated_ctx()
        extract_booking_result(
            {"success": False, "error_code": "VALIDATION_ERROR"},
            ctx,
        )
        assert ctx.pending_recommendations == ["Hidratación"]

    def test_failure_increments_book_failure_count(self):
        """On failure, book_failure_count is incremented (NOT reset)."""
        ctx = self._populated_ctx()
        extract_booking_result(
            {"success": False, "error_code": "VALIDATION_ERROR"},
            ctx,
        )
        assert ctx.book_failure_count == 1

    def test_slot_taken_failure_preserves_selected_services(self):
        """SLOT_TAKEN clears slots but NOT selected_services."""
        ctx = self._populated_ctx()
        extract_booking_result(
            {"success": False, "error_code": "SLOT_TAKEN"},
            ctx,
        )
        assert ctx.selected_services == ["Corte de Dama", "Tinte"]
        # But offered_slots and selected_slot ARE cleared by SLOT_TAKEN logic
        assert ctx.offered_slots is None
        assert ctx.selected_slot is None

    def test_failure_does_not_set_booking_completed(self):
        """On failure, _booking_completed remains False."""
        ctx = self._populated_ctx()
        extract_booking_result(
            {"success": False, "error_code": "SLOT_TAKEN"},
            ctx,
        )
        assert ctx._booking_completed is False


class TestAudienceHintMapExpansion:
    """Verify the expanded _AUDIENCE_HINT_MAP covers new tokens."""

    def test_senora_maps_to_adult_female(self):
        """extract_service_audience_hint('señora') → 'adult_female'."""
        assert extract_service_audience_hint("señora") == "adult_female"

    def test_senor_maps_to_adult_male(self):
        """extract_service_audience_hint('señor') → 'adult_male'."""
        assert extract_service_audience_hint("señor") == "adult_male"

    def test_chica_maps_to_adult_female(self):
        assert extract_service_audience_hint("chica") == "adult_female"

    def test_chico_maps_to_adult_male(self):
        assert extract_service_audience_hint("chico") == "adult_male"

    def test_para_senora_extracts_hint(self):
        """'para señora' → 'senora' token → adult_female."""
        assert extract_service_audience_hint("para señora") == "adult_female"

    def test_soy_una_senora_extracts_hint(self):
        assert extract_service_audience_hint("soy una señora") == "adult_female"

    def test_existing_dama_still_works(self):
        assert extract_service_audience_hint("dama") == "adult_female"

    def test_existing_caballero_still_works(self):
        assert extract_service_audience_hint("corte caballero") == "adult_male"

    def test_existing_nina_still_works(self):
        assert extract_service_audience_hint("peinado niña") == "child_female"


# ============================================================================
# _apply_resolved_option — metadata propagation (combo-recommendations-fix REQ-1)
# ============================================================================


class TestApplyResolvedOptionMetadata:
    """Path A: _apply_resolved_option copies combo_recommendations + description."""

    def _make_opt(
        self,
        service_name: str = "Cortar",
        service_id: str = "uuid-cortar",
        combo_recommendations: list | None = None,
        description: str | None = None,
        duration_minutes: int | None = 40,
    ) -> dict:
        opt = {
            "service_id": service_id,
            "service_name": service_name,
            "duration_minutes": duration_minutes,
            "category": "HAIRDRESSING",
        }
        if combo_recommendations is not None:
            opt["combo_recommendations"] = combo_recommendations
        if description is not None:
            opt["description"] = description
        return opt

    def test_copies_combo_recommendations(self):
        """Option with combo_recommendations → ctx.pending_recommendations set."""
        ctx = BookingContext()
        opt = self._make_opt(combo_recommendations=["Tratamiento", "Peinado"])
        _apply_resolved_option(ctx, opt, axis="audience", resolved_value="adult_female")
        assert ctx.pending_recommendations == ["Tratamiento", "Peinado"]
        assert ctx.recommendations_shown is False

    def test_copies_description(self):
        """Option with description → stored in ctx.selected_services_details."""
        ctx = BookingContext()
        opt = self._make_opt(description="Incluye lavado y secado")
        _apply_resolved_option(ctx, opt, axis="audience", resolved_value="adult_female")
        # _upsert_service_detail stores entries in selected_services_details
        assert len(ctx.selected_services_details) == 1
        assert ctx.selected_services_details[0]["description"] == "Incluye lavado y secado"
        assert ctx.selected_services_details[0]["name"] == "Cortar"

    def test_empty_recommendations_no_overwrite(self):
        """Option with combo_recommendations=[] → ctx.pending_recommendations stays empty, no crash."""
        ctx = BookingContext()
        opt = self._make_opt(combo_recommendations=[])
        _apply_resolved_option(ctx, opt, axis="audience", resolved_value="adult_female")
        assert ctx.pending_recommendations == []

    def test_none_description_no_crash(self):
        """Option with description=None → no KeyError, no crash."""
        ctx = BookingContext()
        opt = self._make_opt(description=None)
        _apply_resolved_option(ctx, opt, axis="audience", resolved_value="adult_female")
        assert ctx.selected_services_details == []

    def test_does_not_overwrite_existing_recommendations(self):
        """If ctx already has recommendations, don't overwrite with new ones."""
        ctx = BookingContext(pending_recommendations=["Existente"])
        opt = self._make_opt(combo_recommendations=["Nuevo"])
        _apply_resolved_option(ctx, opt, axis="audience", resolved_value="adult_female")
        assert ctx.pending_recommendations == ["Existente"]

    def test_scalar_fields_still_set(self):
        """Existing behavior: scalar fields still set after our addition."""
        ctx = BookingContext()
        opt = self._make_opt(
            service_name="Cortar",
            service_id="uuid-cortar",
            combo_recommendations=["Peinado"],
            description="Incluye lavado",
            duration_minutes=40,
        )
        _apply_resolved_option(ctx, opt, axis="audience", resolved_value="adult_female")
        assert ctx.service_id == "uuid-cortar"
        assert ctx.service_name == "Cortar"
        assert ctx.service_duration_minutes == 40
        assert ctx.selected_services == ["Cortar"]


class TestInlineAutoResolveMetadata:
    """Path B: extract_service_fields auto-resolve inline (audience hint match) copies metadata."""

    def test_inline_auto_resolve_copies_recommendations(self):
        """Shape 2 audience inline auto-resolve propagates combo_recommendations."""
        ctx = BookingContext()
        ctx.service_audience_hint = "dama"
        result = {
            "clarification_needed": {
                "axis": "audience",
                "question_hint": "¿Para quién?",
                "options": [
                    {
                        "label": "Dama",
                        "value": "dama",
                        "service_name": "Cortar",
                        "service_id": "uuid-cortar",
                        "duration_minutes": 40,
                        "combo_recommendations": ["Tratamiento", "Peinado"],
                        "description": "Incluye lavado y secado",
                    },
                    {
                        "label": "Caballero",
                        "value": "caballero",
                        "service_name": "Corte Caballero",
                        "service_id": "uuid-cc",
                        "duration_minutes": 30,
                    },
                ],
            }
        }
        extract_service_fields(result, ctx)
        assert ctx.pending_recommendations == ["Tratamiento", "Peinado"]

    def test_inline_auto_resolve_copies_description(self):
        """Shape 2 audience inline auto-resolve propagates description to service_details."""
        ctx = BookingContext()
        ctx.service_audience_hint = "dama"
        result = {
            "clarification_needed": {
                "axis": "audience",
                "options": [
                    {
                        "label": "Dama",
                        "value": "dama",
                        "service_name": "Cortar",
                        "service_id": "uuid-cortar",
                        "duration_minutes": 40,
                        "description": "Incluye lavado y secado",
                    },
                ],
            }
        }
        extract_service_fields(result, ctx)
        assert len(ctx.selected_services_details) == 1
        assert ctx.selected_services_details[0]["description"] == "Incluye lavado y secado"


# ============================================================================
# Regression tests: booking-resolver-collision (SC-1, SC-3)
# ============================================================================


class TestResolverRemovalRegression:
    """SC-1 regression: resolve_pending_clarification must no longer exist in the pipeline.

    After the booking-resolver-collision fix, the Python pre-resolver was removed.
    The LLM handles all clarification resolution natively via <clarification> context.
    """

    def test_resolve_pending_clarification_not_importable(self):
        """SC-1 guard: resolve_pending_clarification must not exist in tool_extractors module."""
        import agent.modes.tool_extractors as te

        assert not hasattr(te, "resolve_pending_clarification"), (
            "resolve_pending_clarification still exists in tool_extractors — "
            "it must be deleted as part of booking-resolver-collision fix"
        )

    def test_booking_mode_does_not_import_resolver(self):
        """SC-1 guard: booking_mode module must not import resolve_pending_clarification."""
        import ast
        import inspect

        import agent.modes.booking_mode as bm

        source = inspect.getsource(bm)
        tree = ast.parse(source)
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.append(alias.name)
        assert "resolve_pending_clarification" not in imported_names, (
            "booking_mode.py still imports resolve_pending_clarification — "
            "it must be removed as part of booking-resolver-collision fix"
        )


class TestCompoundNameHallucinationRegression:
    """SC-3 regression: compound stylist names must not be corrupted by partial redaction.

    Covers:
    - "Ana María" is NOT redacted to "Ana tu estilista"
    - Individual word tokens of a known stylist are NOT flagged as hallucinated
    - Truly hallucinated names (not in any known stylist's name) ARE still redacted
    """

    def _make_mode(self) -> BookingMode:
        return BookingMode(tools=[], llm_client=MagicMock())

    def test_compound_stylist_not_detected_as_hallucination(self):
        """SC-3: 'Ana María' is a known stylist — 'Ana' and 'María' must NOT be flagged."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana María", "id": "1"},
            ]
        )
        mode = self._make_mode()
        response = "Ana María te atenderá con mucho gusto"

        mode._detect_stylist_hallucination(response, ctx)

        assert ctx.force_stylist_correction is False, (
            "'Ana María' is a known stylist — should NOT trigger hallucination detection"
        )

    def test_compound_name_not_redacted_to_artifact(self):
        """SC-3: Response containing known compound name 'Ana María' must remain intact."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana María", "id": "1"},
            ]
        )
        ctx._last_hallucinated_names = set()
        ctx.force_stylist_correction = False
        mode = self._make_mode()

        # Ensure no hallucination detected first
        response = "Ana María puede atenderte el martes"
        mode._detect_stylist_hallucination(response, ctx)

        # Then ensure redact does not corrupt it
        result = mode._redact_hallucinated_stylists(response, ctx)
        assert "tu estilista" not in result, (
            "'Ana María' must NOT be redacted — it is a known stylist compound name"
        )
        assert "Ana María" in result

    def test_truly_hallucinated_name_still_redacted(self):
        """Compound precision: hallucinated 'Carmen' IS still redacted, known 'Ana María' is not."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana María", "id": "1"},
            ]
        )
        mode = self._make_mode()
        response = "Carmen y Ana María pueden atenderte"

        mode._detect_stylist_hallucination(response, ctx)
        result = mode._redact_hallucinated_stylists(response, ctx)

        # Carmen is hallucinated → redacted
        assert "Carmen" not in result
        assert "[estilista]" in result
        # Ana (token of "Ana María") is NOT redacted
        assert "Ana" in result

    def test_word_token_of_known_stylist_not_flagged(self):
        """Individual word 'Ana' must not be flagged when 'Ana María' is a known stylist."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana María", "id": "1"},
            ]
        )
        mode = self._make_mode()
        # Response mentions "Ana" alone (not the full compound name)
        response = "Ana puede atenderte"

        mode._detect_stylist_hallucination(response, ctx)

        # "Ana" is a token of "Ana María" — should NOT flag hallucination
        assert ctx.force_stylist_correction is False

    def test_short_tokens_do_not_create_false_positives(self):
        """Short tokens like 'de' in 'María de Los Ángeles' are excluded from token matching."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "María de Los Ángeles", "id": "1"},
            ]
        )
        mode = self._make_mode()
        # "De" is capitalized but short — should not protect hallucinated names via token match
        # "Los" is a known token (len=3) so it IS in known_word_tokens
        response = "María de Los Ángeles te atiende"

        mode._detect_stylist_hallucination(response, ctx)

        # All words in response are tokens of the known stylist — no hallucination
        assert ctx.force_stylist_correction is False


# ============================================================================
# _previous_assistant_presented_clarification
# ============================================================================


class TestPreviousAssistantPresentedClarification:
    """Unit tests for the context-guard helper."""

    def _clarification_msg(self) -> dict:
        return {
            "role": "assistant",
            "content": "¿El corte es para...?\n1. Bebé\n2. Niño\n3. Niña\n4. Caballero\n5. Dama",
        }

    def _plain_msg(self) -> dict:
        return {"role": "assistant", "content": "Claro, enseguida te ayudo."}

    def test_returns_true_when_numbered_list_present(self):
        messages = [self._clarification_msg()]
        assert _previous_assistant_presented_clarification(messages) is True

    def test_returns_false_for_plain_assistant_message(self):
        messages = [self._plain_msg()]
        assert _previous_assistant_presented_clarification(messages) is False

    def test_returns_false_when_no_assistant_messages(self):
        messages = [{"role": "user", "content": "Hola"}]
        assert _previous_assistant_presented_clarification(messages) is False

    def test_returns_false_for_empty_messages(self):
        assert _previous_assistant_presented_clarification([]) is False

    def test_checks_last_assistant_message(self):
        """Plain message after clarification → False (most recent is plain)."""
        messages = [self._clarification_msg(), self._plain_msg()]
        assert _previous_assistant_presented_clarification(messages) is False

    def test_ignores_user_messages_between(self):
        """User reply between assistant messages — last assistant has numbered list."""
        messages = [
            self._clarification_msg(),
            {"role": "user", "content": "4"},
        ]
        # The last assistant message IS the clarification one
        assert _previous_assistant_presented_clarification(messages) is True


# ============================================================================
# _resolve_user_clarification_selection
# ============================================================================


def _make_clarification_ctx(n_options: int = 5) -> BookingContext:
    """Return a BookingContext with n clarification options on the audience axis."""
    options = [
        {
            "service_id": f"svc-{i}",
            "service_name": f"Servicio {i}",
            "label": f"Opción {i}",
            "value": f"opcion_{i}",
            "category": "peluqueria",
            "duration_minutes": 30,
            "family": None,
        }
        for i in range(1, n_options + 1)
    ]
    ctx = BookingContext()
    ctx.pending_clarifications = [{"axis": "audience", "options": options}]
    return ctx


def _clarification_messages() -> list[dict]:
    """Return a messages list whose last assistant msg has a numbered clarification list."""
    return [
        {
            "role": "assistant",
            "content": "¿El corte es para...?\n1. Opción 1\n2. Opción 2\n"
            "3. Opción 3\n4. Opción 4\n5. Opción 5",
        },
    ]


def _no_clarification_messages() -> list[dict]:
    """Return a messages list whose last assistant msg has NO numbered list."""
    return [{"role": "assistant", "content": "Claro, dime qué servicio deseas."}]


class TestResolveUserClarificationSelection:
    """Unit tests for _resolve_user_clarification_selection (T5.1)."""

    # ── Happy-path ────────────────────────────────────────────────────────────

    def test_bare_number_resolves(self):
        """Sending '4' with 5 options → resolves to option 4."""
        ctx = _make_clarification_ctx(5)
        msgs = _clarification_messages()
        result = _resolve_user_clarification_selection("4", ctx, msgs)
        assert result is True
        assert ctx.service_id == "svc-4"
        assert ctx.pending_clarifications == []

    def test_number_with_text_resolves(self):
        """'el 2 por favor' with 3 options → resolves to option 2."""
        ctx = _make_clarification_ctx(3)
        msgs = _clarification_messages()
        result = _resolve_user_clarification_selection("el 2 por favor", ctx, msgs)
        assert result is True
        assert ctx.service_id == "svc-2"
        assert ctx.pending_clarifications == []

    def test_label_text_match(self):
        """User sends 'opcion_3' (matches value field) → resolves to option 3."""
        ctx = _make_clarification_ctx(5)
        msgs = _clarification_messages()
        result = _resolve_user_clarification_selection("opcion_3", ctx, msgs)
        assert result is True
        assert ctx.service_id == "svc-3"
        assert ctx.pending_clarifications == []

    def test_no_match_returns_false(self):
        """Unrelated message 'hola' → False; ctx unchanged."""
        ctx = _make_clarification_ctx(3)
        msgs = _clarification_messages()
        result = _resolve_user_clarification_selection("hola", ctx, msgs)
        assert result is False
        assert ctx.service_id is None
        assert len(ctx.pending_clarifications) == 1

    # ── Guard conditions ──────────────────────────────────────────────────────

    def test_guard_empty_pending(self):
        """Empty pending_clarifications → False immediately."""
        ctx = BookingContext()
        ctx.pending_clarifications = []
        result = _resolve_user_clarification_selection("4", ctx)
        assert result is False

    def test_guard_service_already_set(self):
        """service_id already set → False even with valid number."""
        ctx = _make_clarification_ctx(3)
        ctx.service_id = "already-set"
        result = _resolve_user_clarification_selection("2", ctx, _clarification_messages())
        assert result is False
        assert ctx.service_id == "already-set"  # unchanged

    def test_guard_no_clarification_in_history(self):
        """Last assistant message had no numbered list → False."""
        ctx = _make_clarification_ctx(5)
        msgs = _no_clarification_messages()
        result = _resolve_user_clarification_selection("3", ctx, msgs)
        assert result is False
        assert ctx.service_id is None
        assert len(ctx.pending_clarifications) == 1

    # ── Multi-entry preservation ───────────────────────────────────────────────

    def test_preserves_other_pending_entries(self):
        """Queue has 2 entries; resolving first keeps second intact."""
        options_a = [
            {
                "service_id": "svc-a1",
                "service_name": "Servicio A1",
                "label": "A1",
                "value": "a1",
                "category": "peluqueria",
                "duration_minutes": 30,
                "family": None,
            },
            {
                "service_id": "svc-a2",
                "service_name": "Servicio A2",
                "label": "A2",
                "value": "a2",
                "category": "peluqueria",
                "duration_minutes": 30,
                "family": None,
            },
        ]
        options_b = [
            {
                "service_id": "svc-b1",
                "service_name": "Servicio B1",
                "label": "B1",
                "value": "b1",
                "category": "peluqueria",
                "duration_minutes": 45,
                "family": None,
            },
        ]
        ctx = BookingContext()
        entry_a = {"axis": "audience", "options": options_a}
        entry_b = {"axis": "hair_density", "options": options_b}
        ctx.pending_clarifications = [entry_a, entry_b]

        msgs = [{"role": "assistant", "content": "¿Para quién?\n1. A1\n2. A2"}]
        result = _resolve_user_clarification_selection("1", ctx, msgs)

        assert result is True
        assert ctx.service_id == "svc-a1"
        # hair_density entry still pending
        assert len(ctx.pending_clarifications) == 1
        assert ctx.pending_clarifications[0]["axis"] == "hair_density"


# ============================================================================
# _previous_assistant_presented_candidates
# ============================================================================


class TestPreviousAssistantPresentedCandidates:
    """Tests for the guard helper that detects candidate service presentation."""

    def _make_candidates(self) -> list[dict]:
        return [
            {"id": "svc-1", "name": "Corte Dama", "duration_minutes": 45},
            {"id": "svc-2", "name": "Bioterapia Capilar", "duration_minutes": 60},
            {"id": "svc-3", "name": "Tinte Completo", "duration_minutes": 90},
        ]

    def test_candidate_names_present_in_last_assistant_message(self):
        """Returns True when last assistant msg contains ≥2 candidate names."""
        candidates = self._make_candidates()
        messages = [
            {"role": "user", "content": "quiero un servicio"},
            {
                "role": "assistant",
                "content": (
                    "Encontré estas opciones:\n"
                    "1. Corte Dama\n"
                    "2. Bioterapia Capilar\n"
                    "3. Tinte Completo\n"
                    "¿Cuál elegís?"
                ),
            },
        ]
        assert _previous_assistant_presented_candidates(messages, candidates) is True

    def test_no_candidate_names_in_last_assistant_message(self):
        """Returns False when last assistant msg is plain text with no candidate names."""
        candidates = self._make_candidates()
        messages = [
            {"role": "user", "content": "hola"},
            {
                "role": "assistant",
                "content": "¡Hola! ¿En qué te puedo ayudar hoy?",
            },
        ]
        assert _previous_assistant_presented_candidates(messages, candidates) is False

    def test_empty_candidates_list_returns_false(self):
        """Returns False immediately when candidates list is empty."""
        messages = [
            {
                "role": "assistant",
                "content": "1. Corte Dama\n2. Bioterapia",
            },
        ]
        assert _previous_assistant_presented_candidates(messages, []) is False

    def test_only_one_candidate_name_in_message_returns_false(self):
        """Returns False when only 1 candidate name appears (requires ≥2)."""
        candidates = self._make_candidates()
        messages = [
            {
                "role": "assistant",
                "content": "El servicio Corte Dama es muy popular.",
            },
        ]
        assert _previous_assistant_presented_candidates(messages, candidates) is False

    def test_no_assistant_messages_returns_false(self):
        """Returns False when there are no assistant messages."""
        candidates = self._make_candidates()
        messages = [
            {"role": "user", "content": "quiero algo"},
        ]
        assert _previous_assistant_presented_candidates(messages, candidates) is False


# ============================================================================
# _resolve_user_candidate_selection
# ============================================================================


class TestResolveUserCandidateSelection:
    """Tests for the candidate service selection pre-resolver."""

    def _make_candidates(self) -> list[dict]:
        return [
            {"id": "svc-1", "name": "Corte Dama", "duration_minutes": 45, "category": "peluqueria"},
            {
                "id": "svc-2",
                "name": "Bioterapia Capilar",
                "duration_minutes": 60,
                "category": "peluqueria",
            },
            {
                "id": "svc-3",
                "name": "Tinte Completo",
                "duration_minutes": 90,
                "category": "coloracion",
            },
        ]

    def _make_messages_with_candidates(self) -> list[dict]:
        return [
            {"role": "user", "content": "quiero un servicio"},
            {
                "role": "assistant",
                "content": (
                    "Encontré estas opciones:\n"
                    "1. Corte Dama\n"
                    "2. Bioterapia Capilar\n"
                    "3. Tinte Completo\n"
                    "¿Cuál elegís?"
                ),
            },
        ]

    def test_numeric_selection_resolves_by_index(self):
        """User sends '2' → resolves candidate at index 1 (0-based)."""
        ctx = BookingContext()
        ctx.candidate_services = self._make_candidates()
        messages = self._make_messages_with_candidates()

        result = _resolve_user_candidate_selection("2", ctx, messages)

        assert result is True
        assert ctx.service_id == "svc-2"
        assert ctx.service_name == "Bioterapia Capilar"
        assert ctx.candidate_services == []

    def test_service_name_text_match_resolves(self):
        """User sends service name text → resolves via substring match."""
        ctx = BookingContext()
        ctx.candidate_services = self._make_candidates()
        messages = self._make_messages_with_candidates()

        result = _resolve_user_candidate_selection("bioterapia capilar", ctx, messages)

        assert result is True
        assert ctx.service_id == "svc-2"
        assert ctx.service_name == "Bioterapia Capilar"
        assert ctx.candidate_services == []

    def test_no_match_returns_false_and_ctx_unchanged(self):
        """User sends unrelated message → returns False, ctx unchanged."""
        ctx = BookingContext()
        ctx.candidate_services = self._make_candidates()
        messages = self._make_messages_with_candidates()
        original_candidates = list(ctx.candidate_services)

        result = _resolve_user_candidate_selection("¿cuánto cuesta?", ctx, messages)

        assert result is False
        assert ctx.service_id is None
        assert ctx.candidate_services == original_candidates

    def test_guard_empty_candidate_services_returns_false_immediately(self):
        """Returns False immediately when ctx.candidate_services is empty."""
        ctx = BookingContext()
        ctx.candidate_services = []
        messages = self._make_messages_with_candidates()

        result = _resolve_user_candidate_selection("1", ctx, messages)

        assert result is False

    def test_guard_no_presented_candidates_in_history(self):
        """Returns False when last assistant msg does NOT contain candidate names."""
        ctx = BookingContext()
        ctx.candidate_services = self._make_candidates()
        messages = [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "¡Hola! ¿En qué te puedo ayudar?"},
        ]

        result = _resolve_user_candidate_selection("1", ctx, messages)

        assert result is False
        assert ctx.service_id is None
        assert len(ctx.candidate_services) == 3
