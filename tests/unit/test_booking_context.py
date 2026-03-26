"""Unit tests for BookingContext dataclass.

Covers: instantiation, query methods (is_ready_to_book, collected_summary,
missing_summary), serialization (from_mode_context, to_mode_context),
round-trip fidelity, and internal _booking_completed flag behavior.
"""

from __future__ import annotations

import pytest

from agent.modes.booking_context import CLEARABLE_NONE_FIELDS, BookingContext


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════


def _full_context() -> BookingContext:
    """Return a fully populated context for reuse across tests."""
    return BookingContext(
        service_id="svc-001",
        service_name="Corte de Dama",
        service_category="HAIRDRESSING",
        service_duration_minutes=45,
        service_family="corte",
        selected_services=["Corte de Dama"],
        service_audience_hint="adult_female",
        stylist_id="sty-001",
        stylist_name="María",
        prefetched_stylists=[{"name": "María", "next_slot_summary": "Lunes 25 a las 10:00"}],
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
        candidate_services=[],
    )


def _minimal_ready_context() -> BookingContext:
    """Minimum fields needed for is_ready_to_book() == True."""
    return BookingContext(
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
        ctx = BookingContext.from_mode_context({})
        assert ctx.service_id is None
        assert ctx.stylist_id is None
        assert ctx.selected_slot is None
        assert ctx.customer_name is None
        assert ctx.selected_services == []
        assert ctx.prefetched_stylists == []
        assert ctx.candidate_services == []

    def test_full_dict(self):
        original = _full_context()
        ctx = BookingContext.from_mode_context(original.to_mode_context())
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
        ctx = BookingContext.from_mode_context(
            {
                "booking_step": "service_selection",
                "last_intent": "book",
                "unknown_field": True,
                "service_id": "svc-999",
            }
        )
        assert ctx.service_id == "svc-999"
        # No error raised — unknown keys silently dropped

    def test_none_lists_default_to_empty(self):
        """None values for list fields are accepted as-is by the constructor."""
        # from_mode_context passes raw values — None for list fields
        # is valid since the dataclass defaults are only for missing keys
        ctx = BookingContext.from_mode_context(
            {
                "selected_services": None,
                "prefetched_stylists": None,
                "candidate_services": None,
            }
        )
        # None is set directly (not coerced to [])
        assert ctx.selected_services is None
        assert ctx.prefetched_stylists is None

    def test_partial_dict(self):
        ctx = BookingContext.from_mode_context(
            {
                "service_id": "svc-001",
                "customer_name": "Ana",
            }
        )
        assert ctx.service_id == "svc-001"
        assert ctx.customer_name == "Ana"
        assert ctx.stylist_id is None
        assert ctx.selected_slot is None


# ═══════════════════════════════════════════════════════════════════════
# to_mode_context
# ═══════════════════════════════════════════════════════════════════════


class TestToModeContext:
    def test_empty_context_excludes_none_and_empty_collections(self):
        ctx = BookingContext()
        result = ctx.to_mode_context()
        # Non-clearable None and empty list/dict values are excluded
        assert "service_id" not in result
        assert "selected_services" not in result
        assert "candidate_services" not in result
        # CLEARABLE fields (offered_slots, selected_slot) ARE included even when None
        assert "offered_slots" in result
        assert result["offered_slots"] is None
        assert "selected_slot" in result
        assert result["selected_slot"] is None
        # False and 0 ARE serialized (they're meaningful state)
        assert result.get("recommendations_shown") is False
        assert result.get("book_failure_count") == 0

    def test_excludes_none_values(self):
        ctx = BookingContext(service_id="abc")
        result = ctx.to_mode_context()
        assert "service_id" in result
        assert "stylist_id" not in result

    def test_excludes_empty_lists(self):
        ctx = BookingContext(service_id="abc", selected_services=[])
        result = ctx.to_mode_context()
        assert "selected_services" not in result

    def test_excludes_internal_fields(self):
        ctx = BookingContext(service_id="abc")
        ctx._booking_completed = True
        result = ctx.to_mode_context()
        assert "_booking_completed" not in result

    def test_includes_populated_lists(self):
        ctx = BookingContext(selected_services=["Corte de Dama"])
        result = ctx.to_mode_context()
        assert result["selected_services"] == ["Corte de Dama"]

    def test_includes_dict_fields(self):
        slot = {"start_time": "2026-03-25T10:00:00+01:00", "date": "2026-03-25"}
        ctx = BookingContext(selected_slot=slot)
        result = ctx.to_mode_context()
        assert result["selected_slot"] == slot

    def test_excludes_empty_dicts(self):
        """Empty dicts are filtered out just like empty lists (non-clearable fields only)."""
        ctx = BookingContext()
        result = ctx.to_mode_context()
        # Only clearable fields may be None; everything else must be non-falsy
        for key, val in result.items():
            if key in CLEARABLE_NONE_FIELDS:
                continue  # These are allowed to be None
            assert val is not None
            assert val != []
            assert val != {}

    # ── REQ-BAF-1 tests (clearable None serialization) ────────────────────

    def test_clearable_fields_serialized_as_none_when_cleared(self):
        """offered_slots=None → key MUST be present with None value (REQ-BAF-1)."""
        ctx = BookingContext()
        ctx.offered_slots = None  # SLOT_TAKEN clears this
        ctx.selected_slot = None  # SLOT_TAKEN clears this too
        result = ctx.to_mode_context()

        assert "offered_slots" in result
        assert result["offered_slots"] is None
        assert "selected_slot" in result
        assert result["selected_slot"] is None

    def test_clearable_fields_serialized_with_data(self):
        """offered_slots=[...] → key present with full list (regression guard, REQ-BAF-1)."""
        slots = [{"date": "2026-03-25", "time": "10:00", "stylist_name": "María"}]
        ctx = BookingContext(offered_slots=slots)
        result = ctx.to_mode_context()

        assert "offered_slots" in result
        assert result["offered_slots"] == slots

    def test_clearable_none_fields_constant_correct(self):
        """CLEARABLE_NONE_FIELDS contains exactly offered_slots and selected_slot."""
        assert CLEARABLE_NONE_FIELDS == frozenset({"offered_slots", "selected_slot"})


# ═══════════════════════════════════════════════════════════════════════
# Round-trip fidelity
# ═══════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    def test_round_trip_full_context(self):
        """from_mode_context(ctx.to_mode_context()) preserves all non-None fields."""
        original = _full_context()
        serialized = original.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

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
        original = BookingContext()
        serialized = original.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)
        assert restored.service_id is None
        assert restored.selected_services == []

    def test_round_trip_partial_context(self):
        original = BookingContext(
            service_id="svc-001",
            service_name="Tinte",
            stylist_name="Ana",
        )
        restored = BookingContext.from_mode_context(original.to_mode_context())
        assert restored.service_id == "svc-001"
        assert restored.service_name == "Tinte"
        assert restored.stylist_name == "Ana"
        assert restored.stylist_id is None

    def test_round_trip_clearable_none_after_merge_dicts(self):
        """REQ-BAF-1: Round-trip fidelity after simulated merge_dicts with None clearable field.

        Simulates the full SLOT_TAKEN recovery cycle:
        1. Previous turn set offered_slots = [old slots] in mode_context
        2. SLOT_TAKEN clears offered_slots = None on context
        3. to_mode_context() includes {"offered_slots": None}
        4. merge_dicts({offered_slots: [old]}, {offered_slots: None}) = {offered_slots: None}
        5. from_mode_context() reconstructs ctx with offered_slots = None
        """
        # Step 1: simulate stale state in mode_context (what LangGraph has stored)
        stale_state = {"offered_slots": [{"date": "2026-03-24", "time": "10:00"}]}

        # Step 2-3: SLOT_TAKEN handler cleared offered_slots, to_mode_context returns None
        cleared_ctx = BookingContext()
        cleared_ctx.offered_slots = None
        update_dict = cleared_ctx.to_mode_context()
        assert "offered_slots" in update_dict
        assert update_dict["offered_slots"] is None

        # Step 4: simulate merge_dicts (shallow merge — update wins)
        merged = {**stale_state, **update_dict}
        assert merged["offered_slots"] is None

        # Step 5: from_mode_context reads back correctly
        restored = BookingContext.from_mode_context(merged)
        assert restored.offered_slots is None  # Stale value overwritten


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
        ctx = BookingContext()
        assert ctx.is_ready_to_book() is False


# ═══════════════════════════════════════════════════════════════════════
# collected_summary
# ═══════════════════════════════════════════════════════════════════════


class TestCollectedSummary:
    def test_empty(self):
        ctx = BookingContext()
        assert ctx.collected_summary() == "(ningún dato recogido todavía)"

    def test_service_only(self):
        ctx = BookingContext(
            service_name="Corte de Dama",
            service_duration_minutes=45,
            service_category="HAIRDRESSING",
        )
        summary = ctx.collected_summary()
        assert "✅ Servicio: Corte de Dama — 45 min — HAIRDRESSING" in summary

    def test_service_without_duration(self):
        ctx = BookingContext(service_name="Tinte")
        summary = ctx.collected_summary()
        assert "✅ Servicio: Tinte" in summary
        assert "min" not in summary

    def test_stylist_line(self):
        ctx = BookingContext(stylist_name="María")
        summary = ctx.collected_summary()
        assert "✅ Estilista: María" in summary

    def test_slot_with_date_and_time(self):
        ctx = BookingContext(
            selected_slot={
                "date": "2026-03-25",
                "time": "10:00",
                "start_time": "2026-03-25T10:00:00+01:00",
            }
        )
        summary = ctx.collected_summary()
        assert "✅ Horario: 2026-03-25 a las 10:00" in summary

    def test_customer_name(self):
        ctx = BookingContext(customer_name="Pepe")
        summary = ctx.collected_summary()
        assert "✅ Nombre: Pepe" in summary

    def test_notes(self):
        ctx = BookingContext(notes="Sin alergia")
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
        ctx = BookingContext(
            service_name="Corte de Dama",
            selected_services=["Corte de Dama", "Tinte", "Peinado"],
        )
        summary = ctx.collected_summary()
        assert "✅ Servicios adicionales: Tinte, Peinado" in summary

    def test_no_additional_services_when_single(self):
        """Single selected service does NOT show additional services line."""
        ctx = BookingContext(
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
        ctx = BookingContext()
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
        ctx = BookingContext(
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
        ctx = BookingContext(
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
        ctx = BookingContext()
        assert ctx._booking_completed is False

    def test_not_in_repr(self):
        ctx = BookingContext()
        assert "_booking_completed" not in repr(ctx)

    def test_excluded_from_to_mode_context(self):
        ctx = BookingContext(service_id="abc")
        ctx._booking_completed = True
        d = ctx.to_mode_context()
        assert "_booking_completed" not in d

    def test_not_restored_from_mode_context(self):
        """_booking_completed is ephemeral — not round-tripped."""
        ctx = BookingContext(service_id="abc")
        ctx._booking_completed = True
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert restored._booking_completed is False


# ═══════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_offered_slots_none_vs_empty(self):
        """offered_slots can be None (default) or a list."""
        ctx = BookingContext()
        assert ctx.offered_slots is None

        ctx2 = BookingContext(offered_slots=[])
        assert ctx2.offered_slots == []

    def test_recurrent_stylist_hint(self):
        """recurrent_stylist_hint field exists and serializes."""
        ctx = BookingContext(recurrent_stylist_hint="María")
        d = ctx.to_mode_context()
        assert d["recurrent_stylist_hint"] == "María"
        restored = BookingContext.from_mode_context(d)
        assert restored.recurrent_stylist_hint == "María"

    def test_pending_clarifications_round_trip(self):
        clarification = {
            "axis": "audience",
            "question_hint": "¿Es para caballero o dama?",
            "options": [
                {"label": "Dama", "value": "adult_female"},
                {"label": "Caballero", "value": "adult_male"},
            ],
        }
        ctx = BookingContext(pending_clarifications=[clarification])
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert restored.pending_clarifications == [clarification]

    def test_candidate_services_round_trip(self):
        candidates = [
            {"name": "Corte de Dama", "id": "svc-001"},
            {"name": "Corte Caballero", "id": "svc-002"},
        ]
        ctx = BookingContext(candidate_services=candidates)
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert restored.candidate_services == candidates

    def test_service_audience_hint_serializes(self):
        ctx = BookingContext(service_audience_hint="adult_female")
        d = ctx.to_mode_context()
        assert d["service_audience_hint"] == "adult_female"

    def test_soonest_any_slot_serializes(self):
        ctx = BookingContext(soonest_any_slot="Lunes 25 a las 10:00")
        d = ctx.to_mode_context()
        assert d["soonest_any_slot"] == "Lunes 25 a las 10:00"


# ═══════════════════════════════════════════════════════════════════════
# reset_transient
# ═══════════════════════════════════════════════════════════════════════


class TestResetTransient:
    """Task 4.1: Unit tests for BookingContext.reset_transient()."""

    def _full_transient_context(self) -> BookingContext:
        """Return a context with all transient fields populated."""
        return BookingContext(
            # Identity fields (must NOT be cleared)
            service_id="svc-001",
            service_name="Corte de Dama",
            service_category="HAIRDRESSING",
            service_duration_minutes=45,
            service_family="corte",
            stylist_id="sty-001",
            stylist_name="María",
            customer_name="Pepe",
            customer_id="cust-001",
            selected_slot={"start_time": "2026-03-25T10:00:00+01:00"},
            offered_slots=[{"time": "10:00", "stylist": "María"}],
            # Transient fields (MUST be cleared)
            selected_services=["Corte de Dama", "Tinte"],
            selected_services_details=[{"name": "Corte de Dama", "duration": 45}],
            pending_clarifications=[{"axis": "audience", "options": []}],
            candidate_services=[{"id": "x", "name": "X"}],
            service_audience_hint="adult_female",
            notes="Sin alergia",
            prefetched_stylists=[{"name": "María"}],
            soonest_any_slot="Lunes 25 a las 10:00 con María",
            recurrent_stylist_hint="María",
            pending_recommendations=["Tinte"],
            recommendations_shown=True,
            recommendations_declined=True,
            book_failure_count=3,
            needs_availability_refresh=True,
            services_locked=True,
        )

    def test_reset_transient_clears_selected_services(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.selected_services == []

    def test_reset_transient_clears_selected_services_details(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.selected_services_details == []

    def test_reset_transient_clears_pending_clarifications(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.pending_clarifications == []

    def test_reset_transient_clears_candidate_services(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.candidate_services == []

    def test_reset_transient_clears_service_audience_hint(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.service_audience_hint is None

    def test_reset_transient_clears_notes(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.notes is None

    def test_reset_transient_clears_prefetched_stylists(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.prefetched_stylists == []

    def test_reset_transient_clears_soonest_any_slot(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.soonest_any_slot is None

    def test_reset_transient_clears_recurrent_stylist_hint(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.recurrent_stylist_hint is None

    def test_reset_transient_clears_pending_recommendations(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.pending_recommendations == []

    def test_reset_transient_resets_recommendations_shown(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.recommendations_shown is False

    def test_reset_transient_resets_recommendations_declined(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.recommendations_declined is False

    def test_reset_transient_resets_book_failure_count(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.book_failure_count == 0

    def test_reset_transient_resets_needs_availability_refresh(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.needs_availability_refresh is False

    def test_reset_transient_resets_services_locked(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.services_locked is False

    def test_reset_transient_preserves_service_id(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.service_id == "svc-001"

    def test_reset_transient_preserves_service_name(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.service_name == "Corte de Dama"

    def test_reset_transient_preserves_service_category(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.service_category == "HAIRDRESSING"

    def test_reset_transient_preserves_service_duration_minutes(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.service_duration_minutes == 45

    def test_reset_transient_preserves_service_family(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.service_family == "corte"

    def test_reset_transient_preserves_stylist_id(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.stylist_id == "sty-001"

    def test_reset_transient_preserves_stylist_name(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.stylist_name == "María"

    def test_reset_transient_preserves_customer_name(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.customer_name == "Pepe"

    def test_reset_transient_preserves_customer_id(self):
        ctx = self._full_transient_context()
        ctx.reset_transient()
        assert ctx.customer_id == "cust-001"

    def test_reset_transient_all_15_fields_cleared(self):
        """Integration test: all 15 transient fields are cleared in one call."""
        ctx = self._full_transient_context()
        ctx.reset_transient()

        # All 15 transient fields must be at default
        assert ctx.selected_services == []
        assert ctx.selected_services_details == []
        assert ctx.pending_clarifications == []
        assert ctx.candidate_services == []
        assert ctx.service_audience_hint is None
        assert ctx.notes is None
        assert ctx.prefetched_stylists == []
        assert ctx.soonest_any_slot is None
        assert ctx.recurrent_stylist_hint is None
        assert ctx.pending_recommendations == []
        assert ctx.recommendations_shown is False
        assert ctx.recommendations_declined is False
        assert ctx.book_failure_count == 0
        assert ctx.needs_availability_refresh is False
        assert ctx.services_locked is False

    def test_reset_transient_idempotent(self):
        """Calling reset_transient twice is safe."""
        ctx = self._full_transient_context()
        ctx.reset_transient()
        ctx.reset_transient()  # Should not raise
        assert ctx.selected_services == []
        assert ctx.book_failure_count == 0

    def test_reset_transient_on_empty_context(self):
        """Calling reset_transient on a fresh context is a no-op."""
        ctx = BookingContext()
        ctx.reset_transient()  # Should not raise
        assert ctx.selected_services == []
        assert ctx.book_failure_count == 0


# ═══════════════════════════════════════════════════════════════════════
# collected_summary — audience hint (Task 4.3)
# ═══════════════════════════════════════════════════════════════════════


class TestCollectedSummaryAudience:
    """Task 4.3: collected_summary() includes audience hint line."""

    def test_audience_hint_adult_female_shows_dama(self):
        """service_audience_hint='adult_female' → '✅ Audiencia: dama'."""
        ctx = BookingContext(service_audience_hint="adult_female")
        summary = ctx.collected_summary()
        assert "✅ Audiencia: dama" in summary

    def test_audience_hint_adult_male_shows_caballero(self):
        """service_audience_hint='adult_male' → '✅ Audiencia: caballero'."""
        ctx = BookingContext(service_audience_hint="adult_male")
        summary = ctx.collected_summary()
        assert "✅ Audiencia: caballero" in summary

    def test_audience_hint_child_male_shows_nino(self):
        ctx = BookingContext(service_audience_hint="child_male")
        summary = ctx.collected_summary()
        assert "✅ Audiencia: niño" in summary

    def test_audience_hint_child_female_shows_nina(self):
        ctx = BookingContext(service_audience_hint="child_female")
        summary = ctx.collected_summary()
        assert "✅ Audiencia: niña" in summary

    def test_audience_hint_baby_shows_bebe(self):
        ctx = BookingContext(service_audience_hint="baby")
        summary = ctx.collected_summary()
        assert "✅ Audiencia: bebé" in summary

    def test_audience_hint_none_no_audiencia_line(self):
        """When service_audience_hint is None, no Audiencia line appears."""
        ctx = BookingContext(service_name="Corte de Dama")
        summary = ctx.collected_summary()
        assert "Audiencia" not in summary

    def test_audience_hint_unknown_value_falls_back_to_raw(self):
        """Unknown hint value falls back to the raw string."""
        ctx = BookingContext(service_audience_hint="unknown_value")
        summary = ctx.collected_summary()
        assert "✅ Audiencia: unknown_value" in summary

    def test_audience_hint_appears_in_full_context(self):
        """_full_context() has audience_hint set — confirm it appears in summary."""
        ctx = BookingContext(
            service_name="Corte de Dama",
            service_audience_hint="adult_female",
            stylist_name="María",
            customer_name="Pepe",
        )
        summary = ctx.collected_summary()
        assert "✅ Audiencia: dama" in summary
        assert "✅ Servicio: Corte de Dama" in summary
        assert "✅ Estilista: María" in summary
        assert "✅ Nombre: Pepe" in summary


# ═══════════════════════════════════════════════════════════════════════
# collected_summary — P4 fallback (service_name=None with selected_services)
# ═══════════════════════════════════════════════════════════════════════


class TestCollectedSummaryFallbackServiceName:
    """P4 fix: when service_name is None but selected_services has entries,
    collected_summary() should use the first entry from selected_services."""

    def test_fallback_to_first_selected_service(self):
        """service_name=None, selected_services=['Corte de Dama'] → shows 'Corte de Dama'."""
        ctx = BookingContext(
            service_name=None,
            selected_services=["Corte de Dama"],
        )
        summary = ctx.collected_summary()
        assert "✅ Servicio: Corte de Dama" in summary

    def test_fallback_with_duration_and_category(self):
        """Fallback service name also renders duration and category."""
        ctx = BookingContext(
            service_name=None,
            selected_services=["Tinte Raíz"],
            service_duration_minutes=60,
            service_category="HAIRDRESSING",
        )
        summary = ctx.collected_summary()
        assert "✅ Servicio: Tinte Raíz — 60 min — HAIRDRESSING" in summary

    def test_no_fallback_when_service_name_present(self):
        """When service_name IS set, it takes priority over selected_services."""
        ctx = BookingContext(
            service_name="Corte Premium",
            selected_services=["Corte de Dama"],
        )
        summary = ctx.collected_summary()
        assert "✅ Servicio: Corte Premium" in summary
        assert "Corte de Dama" not in summary.split("\n")[0]  # Not in the service line

    def test_no_service_line_when_both_empty(self):
        """When both are empty/None, no service line appears."""
        ctx = BookingContext(
            service_name=None,
            selected_services=[],
        )
        summary = ctx.collected_summary()
        assert "✅ Servicio:" not in summary

    def test_fallback_with_multiple_selected_services(self):
        """When multiple services selected, fallback uses the first one."""
        ctx = BookingContext(
            service_name=None,
            selected_services=["Corte de Dama", "Tinte", "Peinado"],
        )
        summary = ctx.collected_summary()
        assert "✅ Servicio: Corte de Dama" in summary
        # Additional services should also be rendered
        assert "✅ Servicios adicionales: Tinte, Peinado" in summary


# ═══════════════════════════════════════════════════════════════════════
# T-10: missing_summary — customer_id conditional
# ═══════════════════════════════════════════════════════════════════════


class TestMissingSummaryCustomerId:
    """T-07 / T-10: customer_id appears in missing_summary() ONLY when
    customer_name is set but customer_id is not yet collected.

    This guides the LLM to call manage_customer before book() — but only
    after it already knows the customer's name."""

    def test_customer_id_shown_when_name_present_but_no_id(self):
        """customer_name set, customer_id None → 'customer_id' in missing text.

        Note: missing_summary() applies .capitalize() to label strings, so the
        output will contain 'Customer_id' (capital C). We compare case-insensitively.
        """
        ctx = BookingContext(
            service_name="Corte de Dama",
            stylist_id="sty-001",
            offered_slots=[{"time": "10:00"}],
            customer_name="María",
            customer_id=None,
        )

        summary = ctx.missing_summary()

        assert "customer_id" in summary.lower()

    def test_customer_id_not_shown_when_no_name_either(self):
        """customer_name None, customer_id None → 'customer_id' NOT in missing text.

        We don't ask for the ID before we even know the name."""
        ctx = BookingContext(
            service_name="Corte de Dama",
            stylist_id="sty-001",
            offered_slots=[{"time": "10:00"}],
            customer_name=None,
            customer_id=None,
        )

        summary = ctx.missing_summary()

        assert "customer_id" not in summary.lower()
        # 'nombre' should still be listed as missing
        assert "nombre" in summary.lower()

    def test_customer_id_not_shown_when_id_present(self):
        """customer_name set, customer_id set → 'customer_id' NOT in missing text."""
        ctx = BookingContext(
            service_name="Corte de Dama",
            stylist_id="sty-001",
            offered_slots=[{"time": "10:00"}],
            customer_name="María",
            customer_id="cust-001",
        )

        summary = ctx.missing_summary()

        assert "customer_id" not in summary.lower()


# ═══════════════════════════════════════════════════════════════════════
# T-10: confirmation_summary_sent field (F-2)
# ═══════════════════════════════════════════════════════════════════════


class TestConfirmationSummarySent:
    """T-10: confirmation_summary_sent field default, serialization, and reset."""

    def test_field_default_false(self):
        """BookingContext() has confirmation_summary_sent=False by default."""
        ctx = BookingContext()
        assert ctx.confirmation_summary_sent is False

    def test_field_serializes(self):
        """to_mode_context() includes confirmation_summary_sent when True."""
        ctx = BookingContext(confirmation_summary_sent=True)
        result = ctx.to_mode_context()
        assert "confirmation_summary_sent" in result
        assert result["confirmation_summary_sent"] is True

    def test_field_serializes_false(self):
        """to_mode_context() includes confirmation_summary_sent=False (meaningful state)."""
        ctx = BookingContext()
        result = ctx.to_mode_context()
        # False is a meaningful value — must be serialized
        assert "confirmation_summary_sent" in result
        assert result["confirmation_summary_sent"] is False

    def test_field_deserializes(self):
        """from_mode_context() restores confirmation_summary_sent=True correctly."""
        ctx = BookingContext.from_mode_context({"confirmation_summary_sent": True})
        assert ctx.confirmation_summary_sent is True

    def test_field_deserializes_false(self):
        """from_mode_context() restores confirmation_summary_sent=False correctly."""
        ctx = BookingContext.from_mode_context({"confirmation_summary_sent": False})
        assert ctx.confirmation_summary_sent is False

    def test_round_trip_true(self):
        """confirmation_summary_sent=True survives to_mode_context → from_mode_context."""
        ctx = BookingContext(confirmation_summary_sent=True)
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert restored.confirmation_summary_sent is True

    def test_resets_on_reset_transient(self):
        """reset_transient() sets confirmation_summary_sent back to False."""
        ctx = BookingContext(confirmation_summary_sent=True)
        ctx.reset_transient()
        assert ctx.confirmation_summary_sent is False
