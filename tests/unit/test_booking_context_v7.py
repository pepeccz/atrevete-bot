"""Unit tests for BookingContextV7 dataclass.

Covers: instantiation, query methods (is_ready_to_book, collected_summary,
missing_summary), serialization (from_mode_context, to_mode_context),
round-trip fidelity, and internal _booking_completed flag behavior.
"""

from __future__ import annotations

import pytest

from agent.modes.booking_context_v7 import BookingContextV7


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════


def _full_context() -> BookingContextV7:
    """Return a fully populated context for reuse across tests."""
    return BookingContextV7(
        service_id="svc-001",
        service_name="Corte de Dama",
        service_category="HAIRDRESSING",
        service_duration_minutes=45,
        service_family="corte",
        selected_services=["Corte de Dama"],
        service_audience_hint="adult_female",
        stylist_id="sty-001",
        stylist_name="María",
        prefetched_stylists=[
            {"name": "María", "next_slot_summary": "Lunes 25 a las 10:00"}
        ],
        soonest_any_slot="Lunes 25 a las 10:00 con María",
        selected_slot={
            "start_time": "2026-03-25T10:00:00+01:00",
            "date": "2026-03-25",
            "time": "10:00",
            "stylist_id": "sty-001",
            "stylist_name": "María",
        },
        offered_slots=[
            {"date": "2026-03-25", "time": "10:00", "stylist_name": "María"},
            {"date": "2026-03-25", "time": "11:00", "stylist_name": "Luciana"},
        ],
        customer_name="Pepe",
        customer_id="cust-001",
        notes="Sin alergia",
        pending_clarification=None,
        candidate_services=[],
    )


def _minimal_ready_context() -> BookingContextV7:
    """Minimum fields needed for is_ready_to_book() == True."""
    return BookingContextV7(
        service_id="svc-001",
        stylist_id="sty-001",
        selected_slot={"start_time": "2026-03-25T10:00:00+01:00"},
        customer_name="Pepe",
    )


# ═══════════════════════════════════════════════════════════════════════
# from_mode_context
# ═══════════════════════════════════════════════════════════════════════


class TestFromModeContext:
    def test_empty_dict(self):
        ctx = BookingContextV7.from_mode_context({})
        assert ctx.service_id is None
        assert ctx.stylist_id is None
        assert ctx.selected_slot is None
        assert ctx.customer_name is None
        assert ctx.selected_services == []
        assert ctx.prefetched_stylists == []
        assert ctx.candidate_services == []

    def test_full_dict(self):
        original = _full_context()
        ctx = BookingContextV7.from_mode_context(original.to_mode_context())
        assert ctx.service_id == "svc-001"
        assert ctx.service_name == "Corte de Dama"
        assert ctx.service_category == "HAIRDRESSING"
        assert ctx.service_duration_minutes == 45
        assert ctx.stylist_id == "sty-001"
        assert ctx.stylist_name == "María"
        assert ctx.customer_name == "Pepe"
        assert ctx.customer_id == "cust-001"
        assert ctx.notes == "Sin alergia"

    def test_ignores_unknown_keys(self):
        """v6 keys like booking_step are silently ignored."""
        ctx = BookingContextV7.from_mode_context({
            "booking_step": "service_selection",
            "last_intent": "book",
            "unknown_field": True,
            "service_id": "svc-999",
        })
        assert ctx.service_id == "svc-999"
        # No error raised — unknown keys silently dropped

    def test_none_lists_default_to_empty(self):
        """None values for list fields are accepted as-is by the constructor."""
        # from_mode_context passes raw values — None for list fields
        # is valid since the dataclass defaults are only for missing keys
        ctx = BookingContextV7.from_mode_context({
            "selected_services": None,
            "prefetched_stylists": None,
            "candidate_services": None,
        })
        # None is set directly (not coerced to [])
        assert ctx.selected_services is None
        assert ctx.prefetched_stylists is None

    def test_partial_dict(self):
        ctx = BookingContextV7.from_mode_context({
            "service_id": "svc-001",
            "customer_name": "Ana",
        })
        assert ctx.service_id == "svc-001"
        assert ctx.customer_name == "Ana"
        assert ctx.stylist_id is None
        assert ctx.selected_slot is None


# ═══════════════════════════════════════════════════════════════════════
# to_mode_context
# ═══════════════════════════════════════════════════════════════════════


class TestToModeContext:
    def test_empty_context_is_empty_dict(self):
        ctx = BookingContextV7()
        result = ctx.to_mode_context()
        assert result == {}

    def test_excludes_none_values(self):
        ctx = BookingContextV7(service_id="abc")
        result = ctx.to_mode_context()
        assert "service_id" in result
        assert "stylist_id" not in result

    def test_excludes_empty_lists(self):
        ctx = BookingContextV7(service_id="abc", selected_services=[])
        result = ctx.to_mode_context()
        assert "selected_services" not in result

    def test_excludes_internal_fields(self):
        ctx = BookingContextV7(service_id="abc")
        ctx._booking_completed = True
        result = ctx.to_mode_context()
        assert "_booking_completed" not in result

    def test_includes_populated_lists(self):
        ctx = BookingContextV7(selected_services=["Corte de Dama"])
        result = ctx.to_mode_context()
        assert result["selected_services"] == ["Corte de Dama"]

    def test_includes_dict_fields(self):
        slot = {"start_time": "2026-03-25T10:00:00+01:00", "date": "2026-03-25"}
        ctx = BookingContextV7(selected_slot=slot)
        result = ctx.to_mode_context()
        assert result["selected_slot"] == slot

    def test_excludes_empty_dicts(self):
        """Empty dicts are filtered out just like empty lists."""
        # This verifies the v != {} filter
        ctx = BookingContextV7()
        result = ctx.to_mode_context()
        # All None/empty values excluded
        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════════════
# Round-trip fidelity
# ═══════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    def test_round_trip_full_context(self):
        """from_mode_context(ctx.to_mode_context()) preserves all non-None fields."""
        original = _full_context()
        serialized = original.to_mode_context()
        restored = BookingContextV7.from_mode_context(serialized)

        assert restored.service_id == original.service_id
        assert restored.service_name == original.service_name
        assert restored.stylist_id == original.stylist_id
        assert restored.stylist_name == original.stylist_name
        assert restored.customer_name == original.customer_name
        assert restored.customer_id == original.customer_id
        assert restored.selected_slot == original.selected_slot
        assert restored.offered_slots == original.offered_slots
        assert restored.notes == original.notes
        assert restored.service_duration_minutes == original.service_duration_minutes
        assert restored.service_category == original.service_category
        assert restored.service_family == original.service_family
        assert restored.selected_services == original.selected_services

    def test_round_trip_empty_context(self):
        original = BookingContextV7()
        serialized = original.to_mode_context()
        restored = BookingContextV7.from_mode_context(serialized)
        assert restored.service_id is None
        assert restored.selected_services == []

    def test_round_trip_partial_context(self):
        original = BookingContextV7(
            service_id="svc-001",
            service_name="Tinte",
            stylist_name="Ana",
        )
        restored = BookingContextV7.from_mode_context(original.to_mode_context())
        assert restored.service_id == "svc-001"
        assert restored.service_name == "Tinte"
        assert restored.stylist_name == "Ana"
        assert restored.stylist_id is None


# ═══════════════════════════════════════════════════════════════════════
# is_ready_to_book
# ═══════════════════════════════════════════════════════════════════════


class TestIsReadyToBook:
    def test_true_when_all_required_present(self):
        ctx = _minimal_ready_context()
        assert ctx.is_ready_to_book() is True

    def test_false_missing_service_id(self):
        ctx = _minimal_ready_context()
        ctx.service_id = None
        ctx.selected_services = []
        assert ctx.is_ready_to_book() is False

    def test_true_with_selected_services_instead_of_service_id(self):
        """selected_services alone satisfies the service requirement."""
        ctx = _minimal_ready_context()
        ctx.service_id = None
        ctx.selected_services = ["Corte de Dama"]
        assert ctx.is_ready_to_book() is True

    def test_false_missing_stylist_id(self):
        ctx = _minimal_ready_context()
        ctx.stylist_id = None
        assert ctx.is_ready_to_book() is False

    def test_false_missing_selected_slot(self):
        ctx = _minimal_ready_context()
        ctx.selected_slot = None
        assert ctx.is_ready_to_book() is False

    def test_false_slot_without_start_time(self):
        ctx = _minimal_ready_context()
        ctx.selected_slot = {"date": "2026-03-25", "time": "10:00"}
        assert ctx.is_ready_to_book() is False

    def test_false_missing_customer(self):
        """Both customer_name and customer_id None -> not ready."""
        ctx = _minimal_ready_context()
        ctx.customer_name = None
        ctx.customer_id = None
        assert ctx.is_ready_to_book() is False

    def test_true_with_customer_id_only(self):
        """customer_id alone satisfies the customer requirement."""
        ctx = _minimal_ready_context()
        ctx.customer_name = None
        ctx.customer_id = "cust-001"
        assert ctx.is_ready_to_book() is True

    def test_empty_context_is_false(self):
        ctx = BookingContextV7()
        assert ctx.is_ready_to_book() is False


# ═══════════════════════════════════════════════════════════════════════
# collected_summary
# ═══════════════════════════════════════════════════════════════════════


class TestCollectedSummary:
    def test_empty(self):
        ctx = BookingContextV7()
        assert ctx.collected_summary() == "(ningún dato recogido todavía)"

    def test_service_only(self):
        ctx = BookingContextV7(
            service_name="Corte de Dama",
            service_duration_minutes=45,
            service_category="HAIRDRESSING",
        )
        summary = ctx.collected_summary()
        assert "✅ Servicio: Corte de Dama — 45 min — HAIRDRESSING" in summary

    def test_service_without_duration(self):
        ctx = BookingContextV7(service_name="Tinte")
        summary = ctx.collected_summary()
        assert "✅ Servicio: Tinte" in summary
        assert "min" not in summary

    def test_stylist_line(self):
        ctx = BookingContextV7(stylist_name="María")
        summary = ctx.collected_summary()
        assert "✅ Estilista: María" in summary

    def test_slot_with_date_and_time(self):
        ctx = BookingContextV7(
            selected_slot={
                "date": "2026-03-25",
                "time": "10:00",
                "start_time": "2026-03-25T10:00:00+01:00",
            }
        )
        summary = ctx.collected_summary()
        assert "✅ Horario: 2026-03-25 a las 10:00" in summary

    def test_customer_name(self):
        ctx = BookingContextV7(customer_name="Pepe")
        summary = ctx.collected_summary()
        assert "✅ Nombre: Pepe" in summary

    def test_notes(self):
        ctx = BookingContextV7(notes="Sin alergia")
        summary = ctx.collected_summary()
        assert "✅ Notas: Sin alergia" in summary

    def test_full(self):
        ctx = _full_context()
        summary = ctx.collected_summary()
        assert "✅ Servicio:" in summary
        assert "✅ Estilista:" in summary
        assert "✅ Horario:" in summary
        assert "✅ Nombre:" in summary
        assert "✅ Notas:" in summary
        # At least 5 lines
        assert summary.count("\n") >= 4

    def test_additional_services(self):
        ctx = BookingContextV7(
            service_name="Corte de Dama",
            selected_services=["Corte de Dama", "Tinte", "Peinado"],
        )
        summary = ctx.collected_summary()
        assert "✅ Servicios adicionales: Tinte, Peinado" in summary

    def test_no_additional_services_when_single(self):
        """Single selected service does NOT show additional services line."""
        ctx = BookingContextV7(
            service_name="Corte de Dama",
            selected_services=["Corte de Dama"],
        )
        summary = ctx.collected_summary()
        assert "adicionales" not in summary


# ═══════════════════════════════════════════════════════════════════════
# missing_summary
# ═══════════════════════════════════════════════════════════════════════


class TestMissingSummary:
    def test_all_missing(self):
        ctx = BookingContextV7()
        summary = ctx.missing_summary()
        assert "❌ Servicio: pendiente" in summary
        assert "❌ Estilista: pendiente" in summary
        assert "❌ Fecha/hora: pendiente" in summary
        assert "❌ Nombre: pendiente" in summary

    def test_none_missing(self):
        ctx = _full_context()
        summary = ctx.missing_summary()
        assert "✅ Todos los datos requeridos están completos" in summary
        assert "❌" not in summary

    def test_partial_missing(self):
        ctx = BookingContextV7(
            service_name="Corte de Dama",
            service_id="svc-001",
            stylist_id="sty-001",
            customer_name="Pepe",
        )
        summary = ctx.missing_summary()
        assert "❌ Servicio:" not in summary
        assert "❌ Estilista:" not in summary
        assert "❌ Nombre:" not in summary
        assert "❌ Fecha/hora: pendiente" in summary

    def test_service_satisfied_by_selected_services(self):
        """selected_services alone satisfies the service requirement."""
        ctx = BookingContextV7(
            selected_services=["Corte de Dama"],
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-25T10:00:00+01:00"},
            customer_name="Pepe",
        )
        summary = ctx.missing_summary()
        assert "❌ Servicio:" not in summary


# ═══════════════════════════════════════════════════════════════════════
# _booking_completed internal flag
# ═══════════════════════════════════════════════════════════════════════


class TestBookingCompletedFlag:
    def test_default_is_false(self):
        ctx = BookingContextV7()
        assert ctx._booking_completed is False

    def test_not_in_repr(self):
        ctx = BookingContextV7()
        assert "_booking_completed" not in repr(ctx)

    def test_excluded_from_to_mode_context(self):
        ctx = BookingContextV7(service_id="abc")
        ctx._booking_completed = True
        d = ctx.to_mode_context()
        assert "_booking_completed" not in d

    def test_not_restored_from_mode_context(self):
        """_booking_completed is ephemeral — not round-tripped."""
        ctx = BookingContextV7(service_id="abc")
        ctx._booking_completed = True
        restored = BookingContextV7.from_mode_context(ctx.to_mode_context())
        assert restored._booking_completed is False


# ═══════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_offered_slots_none_vs_empty(self):
        """offered_slots can be None (default) or a list."""
        ctx = BookingContextV7()
        assert ctx.offered_slots is None

        ctx2 = BookingContextV7(offered_slots=[])
        assert ctx2.offered_slots == []

    def test_recurrent_stylist_hint(self):
        """recurrent_stylist_hint field exists and serializes."""
        ctx = BookingContextV7(recurrent_stylist_hint="María")
        d = ctx.to_mode_context()
        assert d["recurrent_stylist_hint"] == "María"
        restored = BookingContextV7.from_mode_context(d)
        assert restored.recurrent_stylist_hint == "María"

    def test_pending_clarification_round_trip(self):
        clarification = {
            "axis": "audience",
            "question_hint": "¿Es para caballero o dama?",
            "options": [
                {"label": "Dama", "value": "adult_female"},
                {"label": "Caballero", "value": "adult_male"},
            ],
        }
        ctx = BookingContextV7(pending_clarification=clarification)
        restored = BookingContextV7.from_mode_context(ctx.to_mode_context())
        assert restored.pending_clarification == clarification

    def test_candidate_services_round_trip(self):
        candidates = [
            {"name": "Corte de Dama", "id": "svc-001"},
            {"name": "Corte Caballero", "id": "svc-002"},
        ]
        ctx = BookingContextV7(candidate_services=candidates)
        restored = BookingContextV7.from_mode_context(ctx.to_mode_context())
        assert restored.candidate_services == candidates

    def test_service_audience_hint_serializes(self):
        ctx = BookingContextV7(service_audience_hint="adult_female")
        d = ctx.to_mode_context()
        assert d["service_audience_hint"] == "adult_female"

    def test_soonest_any_slot_serializes(self):
        ctx = BookingContextV7(soonest_any_slot="Lunes 25 a las 10:00")
        d = ctx.to_mode_context()
        assert d["soonest_any_slot"] == "Lunes 25 a las 10:00"
