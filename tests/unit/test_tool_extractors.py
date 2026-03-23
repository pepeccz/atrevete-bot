"""Unit tests for tool_extractors.py — Phase 2 of booking-mode-v7.

Tests all extractor functions with realistic tool response shapes,
verifying that BookingContextV7 is mutated correctly.
"""

import json

import pytest

from agent.modes.booking_context_v7 import BookingContextV7
from agent.modes.tool_extractors import (
    TOOL_EXTRACTORS,
    _safe_parse,
    apply_all_tool_results,
    extract_booking_result,
    extract_customer_fields,
    extract_service_audience_hint,
    extract_service_fields,
    extract_slot_fields,
    extract_stylist_fields,
    resolve_pending_clarification,
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
        ctx = BookingContextV7()
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

    def test_resolved_service_clears_disambiguation(self):
        ctx = BookingContextV7(
            pending_clarification={"axis": "audience"},
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

        assert ctx.pending_clarification is None
        assert ctx.candidate_services == []

    def test_resolved_service_sets_audience_hint(self):
        ctx = BookingContextV7()
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
        ctx = BookingContextV7(service_audience_hint="child_female")
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
        ctx = BookingContextV7(selected_services=["Barba"])
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
        ctx = BookingContextV7()
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

        assert ctx.pending_clarification is not None
        assert ctx.pending_clarification["axis"] == "hair_density"
        assert len(ctx.pending_clarification["options"]) == 2
        assert ctx.service_id is None  # NOT resolved yet

    def test_audience_clarification_auto_resolves_when_hint_matches(self):
        """When selected_services already has a service and a new search returns
        clarification_needed with axis=audience, auto-resolve inline if the
        service_audience_hint matches an option. This prevents same-turn
        clobbering of resolved services."""
        ctx = BookingContextV7()
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

        # Should auto-resolve without setting pending_clarification
        assert ctx.pending_clarification is None
        assert "Cortar" in ctx.selected_services
        assert "Cultura de Color" in ctx.selected_services
        assert len(ctx.selected_services) == 2

    def test_audience_clarification_not_auto_resolved_without_hint(self):
        """Without service_audience_hint, clarification should be set normally."""
        ctx = BookingContextV7()
        ctx.selected_services = ["Cultura de Color"]
        # No service_audience_hint set
        result = {
            "clarification_needed": {
                "axis": "audience",
                "question_hint": "¿El corte es para caballero o dama?",
                "options": [
                    {"label": "Caballero", "value": "caballero", "service_name": "Corte Caballero", "service_id": "cc1"},
                    {"label": "Dama", "value": "dama", "service_name": "Cortar", "service_id": "cd1"},
                ],
            },
        }
        extract_service_fields(result, ctx)

        assert ctx.pending_clarification is not None
        assert ctx.pending_clarification["axis"] == "audience"

    def test_non_audience_clarification_always_sets_pending(self):
        """Non-audience clarification should always set pending, even with services."""
        ctx = BookingContextV7()
        ctx.selected_services = ["Cultura de Color"]
        ctx.service_audience_hint = "dama"
        result = {
            "clarification_needed": {
                "axis": "hair_density",
                "options": [
                    {"label": "Normal", "value": "normal", "service_name": "Mechas", "service_id": "m1"},
                    {"label": "Largo", "value": "largo", "service_name": "Mechas XL", "service_id": "m2"},
                ],
            },
        }
        extract_service_fields(result, ctx)

        assert ctx.pending_clarification is not None
        assert ctx.pending_clarification["axis"] == "hair_density"


# ============================================================================
# extract_service_fields — Shape 3 (services list)
# ============================================================================


class TestExtractServiceFieldsShape3:
    def test_single_candidate_auto_resolves(self):
        ctx = BookingContextV7()
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
        assert ctx.pending_clarification is None

    def test_multiple_candidates_stored(self):
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
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

    def test_skips_overwrite_when_slots_already_set(self):
        """Guard: offered_slots is NOT overwritten if already populated."""
        ctx = BookingContextV7(
            offered_slots=[
                {"time": "09:00", "stylist": "Ana", "date": "2026-03-26"}
            ]
        )
        new_slots = [
            {"time": "11:00", "stylist": "María", "date": "2026-03-27"}
        ]
        result = {"available_slots": new_slots, "error": None}
        extract_slot_fields(result, ctx)

        # Guard prevents overwrite — original slots preserved
        assert ctx.offered_slots == [{"time": "09:00", "stylist": "Ana", "date": "2026-03-26"}]

    def test_find_next_available_legacy_shape(self):
        """find_next_available with available_stylists (legacy format)."""
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
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

    def test_empty_slots_does_not_overwrite(self):
        """If result has no slots at all, offered_slots stays unchanged."""
        ctx = BookingContextV7(offered_slots=[{"time": "09:00"}])
        result = {
            "available_slots": [],
            "error": None,
        }
        extract_slot_fields(result, ctx)
        # Empty list is falsy, so no overwrite
        assert ctx.offered_slots == [{"time": "09:00"}]


# ============================================================================
# extract_stylist_fields
# ============================================================================


class TestExtractStylistFields:
    def test_stylists_populated(self):
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
        result = {"stylists": [], "count": 0}
        extract_stylist_fields(result, ctx)

        assert ctx.prefetched_stylists == []


# ============================================================================
# extract_customer_fields
# ============================================================================


class TestExtractCustomerFields:
    def test_get_customer_success(self):
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
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
        ctx = BookingContextV7(customer_id="cust-abc", customer_name="Pedro")
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
        """get with non-existent phone — no fields set."""
        ctx = BookingContextV7()
        result = {
            "exists": False,
            "phone": "+34999999999",
            "message": "Customer not found.",
        }
        extract_customer_fields(result, ctx)

        assert ctx.customer_id is None
        assert ctx.customer_name is None

    def test_only_id_set_when_no_name(self):
        ctx = BookingContextV7()
        result = {"id": "cust-abc"}
        extract_customer_fields(result, ctx)

        assert ctx.customer_id == "cust-abc"
        assert ctx.customer_name is None


# ============================================================================
# extract_booking_result
# ============================================================================


class TestExtractBookingResult:
    def test_booking_success(self):
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
        result = {
            "success": False,
            "error_code": "SLOT_TAKEN",
            "error_message": "El horario ya no está disponible.",
            "details": {},
        }
        extract_booking_result(result, ctx)

        assert ctx._booking_completed is False

    def test_booking_ambiguous_service_failure(self):
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
        apply_all_tool_results({}, ctx)
        assert ctx.service_id is None
        assert ctx.customer_id is None

    def test_unknown_tool_ignored(self):
        ctx = BookingContextV7()
        apply_all_tool_results({"query_info": {"some": "data"}}, ctx)
        assert ctx.service_id is None  # No crash, no mutation

    def test_single_tool_routed(self):
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
        result_json = json.dumps({
            "stylists": [
                {"id": "s1", "name": "María", "category": "HAIRDRESSING"},
            ],
            "count": 1,
        })
        apply_all_tool_results({"list_stylists": result_json}, ctx)

        assert len(ctx.prefetched_stylists) == 1

    def test_unparseable_result_skipped(self):
        ctx = BookingContextV7()
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
        }
        assert expected == set(TOOL_EXTRACTORS.keys())


# ============================================================================
# resolve_pending_clarification (Phase 1 — Pending Clarification Resolver)
# ============================================================================


class TestResolvePendingClarification:
    """Test resolve_pending_clarification pre-resolver."""

    def test_no_pending_returns_false(self):
        """No pending_clarification → no-op."""
        ctx = BookingContextV7(
            service_audience_hint="adult_female",
            pending_clarification=None,
        )
        assert resolve_pending_clarification(ctx) is False

    def test_non_audience_axis_returns_false(self):
        """hair_length axis → not auto-resolvable."""
        ctx = BookingContextV7(
            pending_clarification={
                "axis": "hair_length",
                "options": [
                    {
                        "value": "short",
                        "label": "Corto",
                        "service_id": "uuid-1",
                        "service_name": "Corte Corto",
                    },
                ],
            },
            service_audience_hint="adult_female",
        )
        assert resolve_pending_clarification(ctx) is False
        assert ctx.pending_clarification is not None

    def test_no_hint_returns_false(self):
        """Audience axis but no hint → can't resolve."""
        ctx = BookingContextV7(
            pending_clarification={
                "axis": "audience",
                "options": [
                    {
                        "value": "adult_female",
                        "label": "Mujer",
                        "service_id": "uuid-1",
                        "service_name": "Corte Mujer",
                    },
                ],
            },
        )
        assert resolve_pending_clarification(ctx) is False

    def test_audience_match_resolves(self):
        """Audience hint matches option → mutates ctx correctly."""
        ctx = BookingContextV7(
            service_audience_hint="adult_female",
            pending_clarification={
                "axis": "audience",
                "question_hint": "¿Para quién es?",
                "options": [
                    {
                        "value": "adult_female",
                        "label": "Mujer",
                        "service_id": "uuid-1",
                        "service_name": "Corte Mujer",
                        "category": "corte",
                        "duration_minutes": 45,
                    },
                    {
                        "value": "adult_male",
                        "label": "Hombre",
                        "service_id": "uuid-2",
                        "service_name": "Corte Hombre",
                        "category": "corte",
                        "duration_minutes": 30,
                    },
                ],
            },
        )
        result = resolve_pending_clarification(ctx)

        assert result is True
        assert ctx.service_id == "uuid-1"
        assert ctx.service_name == "Corte Mujer"
        assert ctx.service_category == "corte"
        assert ctx.service_duration_minutes == 45
        assert ctx.selected_services == ["Corte Mujer"]
        assert ctx.pending_clarification is None
        assert ctx.candidate_services == []

    def test_audience_match_appends_to_existing_services(self):
        """Second service resolved via clarification appends, not overwrites."""
        ctx = BookingContextV7(
            selected_services=["Tinte Mujer"],
            service_audience_hint="adult_female",
            pending_clarification={
                "axis": "audience",
                "options": [
                    {
                        "value": "adult_female",
                        "label": "Mujer",
                        "service_id": "uuid-corte-f",
                        "service_name": "Corte Mujer",
                    },
                    {
                        "value": "adult_male",
                        "label": "Hombre",
                        "service_id": "uuid-corte-m",
                        "service_name": "Corte Hombre",
                    },
                ],
            },
        )
        result = resolve_pending_clarification(ctx)

        assert result is True
        assert ctx.service_id == "uuid-corte-f"
        assert ctx.service_name == "Corte Mujer"
        assert ctx.selected_services == ["Corte Mujer", "Tinte Mujer"]
        assert ctx.pending_clarification is None

    def test_no_match_returns_false(self):
        """Hint doesn't match any option → leave pending."""
        ctx = BookingContextV7(
            service_audience_hint="baby",
            pending_clarification={
                "axis": "audience",
                "options": [
                    {
                        "value": "adult_female",
                        "label": "Mujer",
                        "service_id": "uuid-1",
                        "service_name": "Corte Mujer",
                    },
                    {
                        "value": "adult_male",
                        "label": "Hombre",
                        "service_id": "uuid-2",
                        "service_name": "Corte Hombre",
                    },
                ],
            },
        )
        result = resolve_pending_clarification(ctx)

        assert result is False
        assert ctx.pending_clarification is not None
        assert ctx.selected_services == []


# ============================================================================
# extract_booking_result — SLOT_TAKEN cleanup (Phase 2)
# ============================================================================


class TestExtractBookingResultSlotTaken:
    """Test SLOT_TAKEN-specific cleanup in extract_booking_result."""

    def test_slot_taken_clears_offered_slots(self):
        """SLOT_TAKEN error should clear offered_slots to force refresh."""
        ctx = BookingContextV7(
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
        ctx = BookingContextV7(
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
        ctx = BookingContextV7(offered_slots=None, book_failure_count=0)
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
        ctx = BookingContextV7(
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
        ctx = BookingContextV7(
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
        ctx = BookingContextV7(selected_services=[])
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
        ctx = BookingContextV7()
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
        ctx = BookingContextV7(pending_recommendations=["Existing Recommendation"])
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
        ctx = BookingContextV7()
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
        ctx = BookingContextV7()
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
        """New BookingContextV7 defaults to services_locked=False."""
        ctx = BookingContextV7()
        assert ctx.services_locked is False

    def test_apply_all_does_not_lock_without_offered_slots(self):
        """apply_all_tool_results does NOT lock when offered_slots is absent."""
        ctx = BookingContextV7()
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

    def test_apply_all_locks_when_offered_slots_present(self):
        """apply_all_tool_results sets services_locked=True when offered_slots exist."""
        ctx = BookingContextV7(
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

        assert ctx.services_locked is True
        assert ctx.selected_services == ["Corte Caballero"]

    def test_extract_service_fields_skips_when_locked(self):
        """When services_locked=True, extract_service_fields does NOT mutate ctx."""
        ctx = BookingContextV7(
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

        # Nothing changed
        assert ctx.service_id == "uuid-corte"
        assert ctx.service_name == "Corte Caballero"
        assert ctx.selected_services == ["Corte Caballero", "Barba"]

    def test_two_services_same_turn_both_resolve(self):
        """Two search_services in same turn: both resolve before lock engages."""
        ctx = BookingContextV7()
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
        """After SLOT_TAKEN retry, re-calling search_services does NOT drop add-ons."""
        ctx = BookingContextV7(
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

        # Both services preserved — Barba NOT dropped
        assert ctx.selected_services == ["Corte Caballero", "Barba"]
        assert ctx.services_locked is True

    def test_services_locked_reset_on_new_context(self):
        """New BookingContextV7 always starts with services_locked=False."""
        ctx = BookingContextV7()
        assert ctx.services_locked is False

    def test_services_locked_survives_serialization(self):
        """services_locked=True persists through to_mode_context/from_mode_context."""
        ctx = BookingContextV7(
            services_locked=True,
            service_id="uuid-corte",
            service_name="Corte Caballero",
            selected_services=["Corte Caballero"],
        )
        serialized = ctx.to_mode_context()
        restored = BookingContextV7.from_mode_context(serialized)

        assert restored.services_locked is True
        assert restored.selected_services == ["Corte Caballero"]

    def test_addon_service_resolves_before_slots_offered(self):
        """Add-on service on a subsequent turn resolves when no offered_slots yet."""
        ctx = BookingContextV7(
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

    def test_services_locked_engages_when_slots_offered_same_turn(self):
        """Lock engages when both selected_services and offered_slots exist."""
        ctx = BookingContextV7()
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

        # Both selected_services and offered_slots present → locked
        assert ctx.services_locked is True
        assert ctx.selected_services == ["Corte Caballero"]
        assert ctx.offered_slots is not None
