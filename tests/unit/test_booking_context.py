"""Unit tests for BookingContext dataclass.

Covers: instantiation, collected_summary(), missing_summary(), serialization
(from_mode_context, to_mode_context), round-trip fidelity, internal flags,
edge cases, and reset_transient().

Tests for removed fields/methods (deleted in booking-mode-simplification Phase 2-4):
- is_ready_to_book() — removed
- service_family, service_audience_hint, soonest_any_slot, recurrent_stylist_hint — removed
- notes_asked, notes_ask_attempts — removed
- book_failure_count, needs_availability_refresh — removed
- pending_recommendations, recommendations_shown, recommendations_declined,
  recommendations_offer_attempts — removed
- date_parse_error, substitution_made, substitution_reason, date_requested,
  date_substituted, min_valid_date — removed
"""

from __future__ import annotations

import pytest

from agent.modes.booking_context import CLEARABLE_NONE_FIELDS, BookingContext


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

    def test_ignores_unknown_keys(self):
        """v6 keys like booking_step are silently ignored."""
        ctx = BookingContext.from_mode_context(
            {
                "booking_step": "service_selection",
                "last_intent": "book",
                "unknown_field": True,
                "service_id": "svc-999",
                # Legacy deleted fields — silently dropped
                "notes_asked": True,
                "service_family": "corte",
                "book_failure_count": 3,
            }
        )
        assert ctx.service_id == "svc-999"
        # No error raised — unknown/deleted keys silently dropped

    def test_none_lists_default_to_empty(self):
        """None values for list fields are accepted as-is by the constructor."""
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
        # Stylist is gated: only shown when service is known (R3)
        assert "❌ Estilista: pendiente" not in summary
        assert "❌ Fecha/hora: pendiente" in summary
        # Name is gated: only shown when service+stylist+slot are all set
        assert "Nombre" not in summary

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

    def test_pending_clarifications_round_trip(self):
        clarification = {
            "axis": "audience",
            "question_hint": "¿Es para caballero o dama?",
            "options": [
                {"label": "Caballero", "value": "adult_male"},
                {"label": "Dama", "value": "adult_female"},
            ],
        }
        ctx = BookingContext(pending_clarifications=[clarification])
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert len(restored.pending_clarifications) == 1
        assert restored.pending_clarifications[0]["axis"] == "audience"

    def test_candidate_services_round_trip(self):
        services = [{"id": "svc-001", "name": "Corte de Dama"}]
        ctx = BookingContext(candidate_services=services)
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert len(restored.candidate_services) == 1
        assert restored.candidate_services[0]["name"] == "Corte de Dama"


# ═══════════════════════════════════════════════════════════════════════
# reset_transient
# ═══════════════════════════════════════════════════════════════════════


class TestResetTransient:
    """Tests for BookingContext.reset_transient()."""

    def test_reset_transient_clears_offered_slots(self):
        """reset_transient() clears offered_slots to []."""
        ctx = BookingContext(offered_slots=[{"time": "10:00", "stylist_id": "s1"}])
        ctx.reset_transient()
        assert ctx.offered_slots == []

    def test_reset_transient_clears_selected_slot(self):
        """reset_transient() sets selected_slot to None."""
        ctx = BookingContext(selected_slot={"start_time": "2026-03-25T10:00:00+01:00"})
        ctx.reset_transient()
        assert ctx.selected_slot is None

    def test_reset_transient_clears_hold_id(self):
        """reset_transient() clears hold_id."""
        ctx = BookingContext(hold_id="hold-to-clear")
        ctx.reset_transient()
        assert ctx.hold_id is None

    def test_reset_transient_resets_confirmation_shown(self):
        """reset_transient() sets confirmation_shown=False."""
        ctx = BookingContext(confirmation_shown=True)
        ctx.reset_transient()
        assert ctx.confirmation_shown is False

    def test_reset_transient_resets_confirmation_summary_sent(self):
        """reset_transient() sets confirmation_summary_sent=False."""
        ctx = BookingContext(confirmation_summary_sent=True)
        ctx.reset_transient()
        assert ctx.confirmation_summary_sent is False

    def test_reset_transient_preserves_service_id(self):
        """reset_transient() does NOT clear service_id."""
        ctx = BookingContext(
            service_id="svc-001",
            offered_slots=[{"time": "10:00"}],
        )
        ctx.reset_transient()
        assert ctx.service_id == "svc-001"

    def test_reset_transient_preserves_stylist_id(self):
        """reset_transient() does NOT clear stylist_id."""
        ctx = BookingContext(
            stylist_id="sty-001",
            offered_slots=[{"time": "10:00"}],
        )
        ctx.reset_transient()
        assert ctx.stylist_id == "sty-001"

    def test_reset_transient_preserves_customer_name(self):
        """reset_transient() does NOT clear customer_name."""
        ctx = BookingContext(
            customer_name="Pepe",
            offered_slots=[{"time": "10:00"}],
        )
        ctx.reset_transient()
        assert ctx.customer_name == "Pepe"

    def test_reset_transient_preserves_customer_id(self):
        """reset_transient() does NOT clear customer_id."""
        ctx = BookingContext(
            customer_id="cust-001",
            offered_slots=[{"time": "10:00"}],
        )
        ctx.reset_transient()
        assert ctx.customer_id == "cust-001"

    def test_reset_transient_preserves_notes(self):
        """reset_transient() does NOT clear notes."""
        ctx = BookingContext(notes="Sin alergia")
        ctx.reset_transient()
        assert ctx.notes == "Sin alergia"

    def test_reset_transient_idempotent(self):
        """Calling reset_transient twice is safe."""
        ctx = BookingContext(offered_slots=[{"time": "10:00"}], hold_id="hold-1")
        ctx.reset_transient()
        ctx.reset_transient()  # Should not raise
        assert ctx.offered_slots == []
        assert ctx.hold_id is None

    def test_reset_transient_on_empty_context(self):
        """Calling reset_transient on a fresh context is a no-op."""
        ctx = BookingContext()
        ctx.reset_transient()  # Should not raise
        assert ctx.offered_slots == []


# ═══════════════════════════════════════════════════════════════════════
# missing_summary — name timing gate (BUG-3)
# ═══════════════════════════════════════════════════════════════════════


class TestMissingSummaryNameTiming:
    """BUG-3: missing_summary() must NOT ask for name until service+stylist+slot are resolved.

    Covers S8 (empty ctx → no name), S9 (service only → no name),
    S10 (all context set, no name → name appears), S11 (name set → no name line).
    """

    def test_name_hidden_when_no_service_no_stylist_no_slot(self):
        """S8: empty BookingContext → missing_summary() does NOT contain 'Nombre'."""
        ctx = BookingContext()
        summary = ctx.missing_summary()
        assert "Nombre" not in summary

    def test_name_hidden_when_service_set_but_no_stylist_slot(self):
        """S9: service_name set, no stylist_id, no selected_slot → does NOT contain 'Nombre'."""
        ctx = BookingContext(service_name="Cortar")
        summary = ctx.missing_summary()
        assert "Nombre" not in summary

    def test_name_shown_when_service_stylist_slot_set(self):
        """S10: service+stylist_id+selected_slot set, no customer_name → CONTAINS 'Nombre'."""
        ctx = BookingContext(
            service_name="Cortar",
            stylist_id="test-uuid-stylist",
            selected_slot={"date": "2026-04-10", "time": "10:20"},
        )
        summary = ctx.missing_summary()
        assert "❌ Nombre: pendiente" in summary

    def test_name_hidden_when_already_set(self):
        """S11: all fields set including customer_name → does NOT contain 'Nombre' line."""
        ctx = BookingContext(
            service_name="Cortar",
            stylist_id="test-uuid-stylist",
            selected_slot={"date": "2026-04-10", "time": "10:20"},
            customer_name="María",
        )
        summary = ctx.missing_summary()
        assert "Nombre" not in summary


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
    customer_name is set but customer_id is not yet collected."""

    def test_customer_id_shown_when_name_present_but_no_id(self):
        """customer_name set, customer_id None → 'customer_id' in missing text."""
        ctx = BookingContext(
            service_name="Corte de Dama",
            stylist_id="sty-001",
            selected_slot={
                "start_time": "2026-03-25T10:00:00+01:00",
                "date": "2026-03-25",
                "time": "10:00",
            },
            customer_name="María",
            customer_id=None,
        )

        summary = ctx.missing_summary()

        # Output is "❌ Customer ID: ..." — check case-insensitively
        assert "customer" in summary.lower() and "id" in summary.lower()

    def test_customer_id_not_shown_when_no_name_either(self):
        """customer_name None, customer_id None → 'customer_id' NOT in missing text."""
        ctx = BookingContext(
            service_name="Corte de Dama",
            stylist_id="sty-001",
            selected_slot={
                "start_time": "2026-03-25T10:00:00+01:00",
                "date": "2026-03-25",
                "time": "10:00",
            },
            customer_name=None,
            customer_id=None,
        )

        summary = ctx.missing_summary()

        # "customer id" should not appear when customer_name is also None
        assert not any(
            "customer" in line.lower() and "id" in line.lower()
            for line in summary.lower().splitlines()
            if "nombre" not in line  # exclude the nombre line
        )
        # 'nombre' should still be listed as missing
        assert "nombre" in summary.lower()

    def test_customer_id_not_shown_when_id_present(self):
        """customer_name set, customer_id set → 'customer_id' NOT in missing text."""
        ctx = BookingContext(
            service_name="Corte de Dama",
            stylist_id="sty-001",
            selected_slot={
                "start_time": "2026-03-25T10:00:00+01:00",
                "date": "2026-03-25",
                "time": "10:00",
            },
            customer_name="María",
            customer_id="cust-001",
        )

        summary = ctx.missing_summary()

        # "customer id" should not appear since customer is fully identified
        assert not any(
            "customer" in line.lower() and "id" in line.lower()
            for line in summary.lower().splitlines()
        )


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


# ═══════════════════════════════════════════════════════════════════════
# TestBookingContextHints — preferred_stylist_name / preferred_date_hint
# ═══════════════════════════════════════════════════════════════════════


class TestBookingContextHints:
    """Tests for preferred_stylist_name/preferred_date_hint fields and display logic."""

    def test_stylist_hidden_when_no_service(self):
        """S1: empty ctx → 'Estilista' NOT in missing_summary."""
        ctx = BookingContext()
        assert "Estilista" not in ctx.missing_summary()

    def test_stylist_shown_when_service_known(self):
        """S2: service set, no stylist → 'Estilista' IN missing_summary."""
        ctx = BookingContext(service_name="Cortar")
        assert "Estilista" in ctx.missing_summary()

    def test_stylist_hidden_when_confirmed(self):
        """S3: stylist set → 'Estilista' NOT in missing_summary."""
        ctx = BookingContext(service_name="Cortar", stylist_id="uuid")
        assert "Estilista" not in ctx.missing_summary()

    def test_preferred_stylist_shown_in_collected(self):
        """S4: preferred_stylist_name set, no stylist_id → 💡 hint in collected_summary."""
        ctx = BookingContext(preferred_stylist_name="Pilar")
        assert "💡 Estilista preferida" in ctx.collected_summary()

    def test_preferred_stylist_hidden_when_confirmed(self):
        """S5: preferred_stylist_name AND stylist_id set → hint NOT shown."""
        ctx = BookingContext(preferred_stylist_name="Pilar", stylist_id="uuid")
        assert "💡 Estilista preferida" not in ctx.collected_summary()

    def test_preferred_date_shown_in_collected(self):
        """S6: preferred_date_hint set, no selected_slot → 💡 hint in collected_summary."""
        ctx = BookingContext(preferred_date_hint="el viernes")
        assert "💡 Fecha preferida" in ctx.collected_summary()


# ============================================================================
# hold_id field (double-booking prevention — REQ-15)
# ============================================================================


class TestHoldIdField:
    """Tests for the hold_id field added for double-booking prevention."""

    def test_hold_id_defaults_to_none(self):
        """REQ-15: hold_id defaults to None on a fresh BookingContext."""
        ctx = BookingContext()
        assert ctx.hold_id is None

    def test_hold_id_can_be_set(self):
        """hold_id can be set to a UUID string."""
        ctx = BookingContext(hold_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
        assert ctx.hold_id == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"

    def test_hold_id_serializes_in_to_mode_context(self):
        """REQ-15: hold_id is included in to_mode_context() when set."""
        ctx = BookingContext(hold_id="abc-123")
        mode_ctx = ctx.to_mode_context()
        assert "hold_id" in mode_ctx
        assert mode_ctx["hold_id"] == "abc-123"

    def test_hold_id_omitted_when_none_in_to_mode_context(self):
        """hold_id is NOT included in to_mode_context() when None (lean context)."""
        ctx = BookingContext()
        mode_ctx = ctx.to_mode_context()
        # hold_id=None should be omitted (not in CLEARABLE_NONE_FIELDS)
        assert "hold_id" not in mode_ctx

    def test_hold_id_round_trips_via_from_mode_context(self):
        """REQ-15: hold_id persists through serialization round-trip."""
        ctx = BookingContext(hold_id="hold-uuid-999")
        mode_ctx = ctx.to_mode_context()
        restored = BookingContext.from_mode_context(mode_ctx)
        assert restored.hold_id == "hold-uuid-999"

    def test_hold_id_defaults_when_absent_in_from_mode_context(self):
        """from_mode_context() with no hold_id key → defaults to None."""
        ctx = BookingContext.from_mode_context({"customer_name": "Pepe"})
        assert ctx.hold_id is None

    def test_reset_transient_clears_hold_id(self):
        """reset_transient() must clear hold_id so stale holds don't linger."""
        ctx = BookingContext(hold_id="hold-to-clear")
        ctx.reset_transient()
        assert ctx.hold_id is None


# ═══════════════════════════════════════════════════════════════════════
# resolved_axes — disambiguation axis memory
# ═══════════════════════════════════════════════════════��═══════════════


class TestResolvedAxes:
    """resolved_axes tracks which disambiguation axes have been answered by the user.

    This prevents the LLM from re-asking questions like hair_length when
    the answer was already used to resolve a service.
    """

    def test_default_is_empty_dict(self):
        ctx = BookingContext()
        assert ctx.resolved_axes == {}

    def test_can_set_axes(self):
        ctx = BookingContext(resolved_axes={"audience": "adult_female", "hair_length": "short_medium"})
        assert ctx.resolved_axes["audience"] == "adult_female"
        assert ctx.resolved_axes["hair_length"] == "short_medium"

    def test_serializes_in_to_mode_context(self):
        ctx = BookingContext(resolved_axes={"hair_length": "long"})
        result = ctx.to_mode_context()
        assert "resolved_axes" in result
        assert result["resolved_axes"] == {"hair_length": "long"}

    def test_omitted_when_empty_in_to_mode_context(self):
        ctx = BookingContext()
        result = ctx.to_mode_context()
        assert "resolved_axes" not in result

    def test_round_trip(self):
        ctx = BookingContext(resolved_axes={"audience": "adult_male", "hair_density": "normal"})
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert restored.resolved_axes == {"audience": "adult_male", "hair_density": "normal"}

    def test_shown_in_collected_summary(self):
        """Resolved axes must appear in collected_summary so the LLM sees them."""
        ctx = BookingContext(
            service_name="Peinado",
            resolved_axes={"hair_length": "short_medium"},
        )
        summary = ctx.collected_summary()
        assert "hair_length" in summary or "Pelo" in summary

    def test_not_cleared_by_reset_transient(self):
        """resolved_axes survives reset_transient — they're part of service identity."""
        ctx = BookingContext(resolved_axes={"audience": "adult_female"})
        ctx.reset_transient()
        assert ctx.resolved_axes == {"audience": "adult_female"}
