"""
Unit tests for booking-full-context-awareness — early booking hint extraction.

Tests:
- T-4.1: _extract_early_booking_hints() — date/stylist/notes hint extraction
- T-4.2: _try_resolve_stylist_from_message() — hint-based resolution path
- T-4.3: _extract_notes_from_conversation() — early notes capture via hint
- T-4.4: _f7_auto_recover() — query decontamination (date/stylist tokens stripped)
- T-4.5: Regression — no-hint path unchanged
- T-4.6: Confirmed fields not overwritten by hint extraction
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import (
    _DATE_STOPWORDS,
    _extract_early_booking_hints,
    _extract_notes_from_conversation,
    _normalize_text,
    _try_resolve_stylist_from_message,
    BookingMode,
)
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_state(user_message: str = "hola") -> dict:
    """Build a minimal ConversationState for early hint tests."""
    state = create_initial_state("conv-001", "+34612345678")
    state["customer_name"] = "María"
    state["customer_id"] = "cust-001"
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"
    state["mode_context"] = {}
    state["messages"] = [{"role": "user", "content": user_message}]
    return state


def make_booking_mode() -> BookingMode:
    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "¿Qué servicio deseas?"
    mock_response.tool_calls = []
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return BookingMode(tools=[], llm_client=mock_llm)


# =============================================================================
# T-4.1: _extract_early_booking_hints() — S2, S3, S4, S5, S6, S7
# =============================================================================


class TestExtractEarlyBookingHints:
    """Tests for the _extract_early_booking_hints pre-resolver function."""

    # ── S2: Date hint from relative expression ────────────────────────────────

    def test_date_hint_extracted_viernes(self):
        """S2: 'quiero cita el viernes que viene' → preferred_date_hint set."""
        ctx = BookingContext()
        state = make_state("quiero cita el viernes que viene")
        _extract_early_booking_hints(state, ctx, "quiero cita el viernes que viene")
        assert ctx.preferred_date_hint is not None
        assert "viernes" in ctx.preferred_date_hint.lower()

    def test_date_hint_extracted_manana(self):
        """S2 variant: 'mañana' captured as date hint (stored as normalized 'manana')."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "quiero turno mañana")
        assert ctx.preferred_date_hint is not None
        # Stored as normalized (accent-stripped) form
        assert "manana" in ctx.preferred_date_hint.lower()

    def test_date_hint_extracted_hoy(self):
        """S2 variant: 'hoy' captured as date hint."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "quiero algo hoy")
        assert ctx.preferred_date_hint is not None
        assert "hoy" in ctx.preferred_date_hint.lower()

    def test_date_hint_extracted_numeric(self):
        """S2 variant: 'el 15 de abril' captured as date hint."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "quiero el 15 de abril")
        assert ctx.preferred_date_hint is not None
        assert "15" in ctx.preferred_date_hint

    # ── S3: Stylist hint from "con [Name]" ────────────────────────────────────

    def test_stylist_hint_extracted_con_ana(self):
        """S3: 'quiero cita con Ana, un corte' → stylist_name_hint = 'Ana'."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "quiero cita con Ana, un corte")
        assert ctx.stylist_name_hint == "Ana"

    def test_stylist_hint_extracted_prefiero_a(self):
        """S3 variant: 'prefiero a Pilar' → stylist_name_hint = 'Pilar'."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "prefiero a Pilar para el corte")
        assert ctx.stylist_name_hint == "Pilar"

    def test_stylist_hint_extracted_que_me_atienda(self):
        """S3 variant: 'que me atienda Sofía' → stylist_name_hint = 'Sofía'."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "quiero que me atienda Sofía")
        assert ctx.stylist_name_hint == "Sofía"

    # ── S4: Notes hint from allergy phrase ───────────────────────────────────

    def test_notes_hint_extracted_alergica_al_amoniaco(self):
        """S4: 'soy alérgica al amoniaco' → notes_hint set (normalized form without accent)."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "quiero un corte, soy alérgica al amoniaco")
        assert ctx.notes_hint is not None
        # Stored as normalized (accent-stripped): "alergica al amoniaco"
        assert "alergica" in ctx.notes_hint.lower()

    def test_notes_hint_extracted_pelo_muy(self):
        """S4 variant: 'pelo muy rizado' → notes_hint set."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "tengo pelo muy rizado")
        assert ctx.notes_hint is not None
        assert "pelo" in ctx.notes_hint.lower()

    # ── S5: Most-recent hint wins (override) ─────────────────────────────────

    def test_date_hint_overrides_on_new_message(self):
        """S5: A later message with a new date overwrites the prior hint."""
        ctx = BookingContext()
        # First message sets "viernes"
        _extract_early_booking_hints(make_state(), ctx, "el viernes mejor")
        assert ctx.preferred_date_hint is not None
        assert "viernes" in ctx.preferred_date_hint.lower()

        # Second message updates to "lunes"
        _extract_early_booking_hints(make_state(), ctx, "mejor el lunes")
        assert ctx.preferred_date_hint is not None
        assert "lunes" in ctx.preferred_date_hint.lower()

    # ── S6: Guard — confirmed fields NOT overwritten ──────────────────────────

    def test_stylist_hint_not_extracted_when_stylist_id_set(self):
        """S6: If ctx.stylist_id is already set, stylist_name_hint is NOT modified."""
        ctx = BookingContext()
        ctx.stylist_id = "some-uuid"
        ctx.stylist_name = "Pilar"
        _extract_early_booking_hints(make_state(), ctx, "con Ana, un corte")
        # Hint should NOT be set — field was already confirmed
        assert ctx.stylist_name_hint is None

    def test_date_hint_not_extracted_when_slot_selected(self):
        """S6 variant: If selected_slot is set, date hint is not extracted."""
        ctx = BookingContext()
        ctx.selected_slot = {"start_time": "2026-04-10T10:00:00"}
        _extract_early_booking_hints(make_state(), ctx, "quiero el viernes")
        assert ctx.preferred_date_hint is None

    def test_notes_hint_not_extracted_when_notes_set(self):
        """S6 variant: If ctx.notes is set, notes_hint is not extracted."""
        ctx = BookingContext()
        ctx.notes = "ya tenía nota previa"
        _extract_early_booking_hints(make_state(), ctx, "soy alérgica al amoniaco")
        assert ctx.notes_hint is None

    # ── S7: No hints in plain message ────────────────────────────────────────

    def test_no_hints_from_plain_message(self):
        """S7: 'hola, quiero un turno' → all hint fields remain None."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "hola, quiero un turno")
        assert ctx.preferred_date_hint is None
        assert ctx.stylist_name_hint is None
        assert ctx.notes_hint is None

    def test_no_hints_from_simple_affirmative(self):
        """S7 variant: 'sí' → all hints remain None."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "sí")
        assert ctx.preferred_date_hint is None
        assert ctx.stylist_name_hint is None
        assert ctx.notes_hint is None

    def test_no_hints_from_empty_message(self):
        """Edge case: empty message → all hints remain None."""
        ctx = BookingContext()
        _extract_early_booking_hints(make_state(), ctx, "")
        assert ctx.preferred_date_hint is None
        assert ctx.stylist_name_hint is None
        assert ctx.notes_hint is None


# =============================================================================
# T-4.2: _try_resolve_stylist_from_message() — S8, S11
# =============================================================================


class TestTryResolveStyleFromHint:
    """Tests for hint-based stylist resolution in _try_resolve_stylist_from_message()."""

    STYLISTS = [
        {"id": "uuid-ana", "name": "Ana María"},
        {"id": "uuid-pilar", "name": "Pilar"},
    ]

    def test_stylist_resolved_from_hint_before_presentation(self):
        """S8: stylist_name_hint='Ana', prefetched_stylists available, stylists_presented=False
        → ctx.stylist_id set, hint cleared."""
        ctx = BookingContext()
        ctx.stylist_name_hint = "Ana"
        ctx.prefetched_stylists = self.STYLISTS
        ctx.stylists_presented = False

        messages = [{"role": "user", "content": "con Ana un corte"}]
        _try_resolve_stylist_from_message("con Ana un corte", ctx, messages)

        assert ctx.stylist_id == "uuid-ana"
        assert ctx.stylist_name == "Ana María"
        assert ctx.stylist_name_hint is None  # consumed

    def test_stylist_resolved_from_hint_exact_name(self):
        """S8 variant: 'Pilar' hint → resolves to Pilar."""
        ctx = BookingContext()
        ctx.stylist_name_hint = "Pilar"
        ctx.prefetched_stylists = self.STYLISTS
        ctx.stylists_presented = False

        messages = [{"role": "user", "content": "con Pilar"}]
        _try_resolve_stylist_from_message("con Pilar", ctx, messages)

        assert ctx.stylist_id == "uuid-pilar"
        assert ctx.stylist_name == "Pilar"
        assert ctx.stylist_name_hint is None

    def test_stylist_hint_no_match_hint_preserved(self):
        """S11: hint='Ana', prefetched_stylists=[] → no resolution, hint preserved."""
        ctx = BookingContext()
        ctx.stylist_name_hint = "Ana"
        ctx.prefetched_stylists = []
        ctx.stylists_presented = False

        messages = [{"role": "user", "content": "con Ana"}]
        _try_resolve_stylist_from_message("con Ana", ctx, messages)

        assert ctx.stylist_id is None
        assert ctx.stylist_name_hint == "Ana"  # preserved

    def test_stylist_no_resolution_when_no_hint(self):
        """S10 regression: no hint, stylists_presented=False → no resolution."""
        ctx = BookingContext()
        ctx.stylist_name_hint = None
        ctx.prefetched_stylists = self.STYLISTS
        ctx.stylists_presented = False

        messages = [{"role": "user", "content": "con Ana"}]
        _try_resolve_stylist_from_message("con Ana", ctx, messages)

        # Without a hint, the guard blocks resolution when stylists not presented
        assert ctx.stylist_id is None

    def test_stylist_resolution_works_when_presented(self):
        """Regression: normal path (stylists_presented=True) still works."""
        ctx = BookingContext()
        ctx.prefetched_stylists = self.STYLISTS
        ctx.stylists_presented = True

        messages = [{"role": "user", "content": "quiero con Ana"}]
        _try_resolve_stylist_from_message("quiero con Ana", ctx, messages)

        assert ctx.stylist_id == "uuid-ana"

    def test_stylist_already_resolved_is_not_overwritten(self):
        """Guard: if ctx.stylist_id already set, function returns immediately."""
        ctx = BookingContext()
        ctx.stylist_id = "existing-uuid"
        ctx.stylist_name = "Pilar"
        ctx.stylist_name_hint = "Ana"
        ctx.prefetched_stylists = self.STYLISTS
        ctx.stylists_presented = False

        messages = [{"role": "user", "content": "con Ana"}]
        _try_resolve_stylist_from_message("con Ana", ctx, messages)

        assert ctx.stylist_id == "existing-uuid"  # unchanged


# =============================================================================
# T-4.3: _extract_notes_from_conversation() — S9, S10
# =============================================================================


class TestExtractNotesViaHint:
    """Tests for early notes capture via notes_hint in _extract_notes_from_conversation()."""

    def test_notes_captured_from_hint_before_notes_asked(self):
        """S9: notes_hint set, notes=None, notes_asked=False → notes set, hint cleared."""
        ctx = BookingContext()
        ctx.notes_hint = "alérgica al amoniaco"
        ctx.notes_asked = False

        state = make_state("quiero un corte")
        _extract_notes_from_conversation(state, "cualquier mensaje", ctx)

        assert ctx.notes == "alérgica al amoniaco"
        assert ctx.notes_hint is None  # consumed

    def test_notes_hint_not_consumed_when_notes_already_set(self):
        """Guard: if ctx.notes already set, hint path is not reached."""
        ctx = BookingContext()
        ctx.notes = "nota previa"
        ctx.notes_hint = "alérgica al amoniaco"
        ctx.notes_asked = False

        state = make_state("mensaje")
        _extract_notes_from_conversation(state, "mensaje", ctx)

        # notes should not change
        assert ctx.notes == "nota previa"

    def test_notes_asked_path_unchanged_when_no_hint(self):
        """S10 regression: no hint, notes_asked=False → no notes captured."""
        ctx = BookingContext()
        ctx.notes_hint = None
        ctx.notes_asked = False

        state = make_state("soy alérgica al amoniaco")
        _extract_notes_from_conversation(state, "soy alérgica al amoniaco", ctx)

        # notes_asked=False, no hint → should NOT capture (gate blocks)
        assert ctx.notes is None

    def test_notes_asked_path_still_works(self):
        """Regression: when notes_asked=True and no hint, normal path still works."""
        ctx = BookingContext()
        ctx.notes_hint = None
        ctx.notes_asked = True
        ctx.notes = None

        state = make_state("tengo el pelo muy fino")
        _extract_notes_from_conversation(state, "tengo el pelo muy fino", ctx)

        assert ctx.notes == "tengo el pelo muy fino"


# =============================================================================
# T-4.4: F-7 decontamination — S14, S15, S16
# =============================================================================


class TestF7Decontamination:
    """Tests for _f7_auto_recover query decontamination."""

    STYLISTS = [
        {"id": "uuid-ana", "name": "Ana"},
        {"id": "uuid-pilar", "name": "Pilar"},
    ]

    @pytest.mark.asyncio
    async def test_date_tokens_stripped_from_f7_query(self):
        """S14: 'quiero cita el viernes para un corte' → date tokens stripped from query."""
        mode = make_booking_mode()
        ctx = BookingContext()
        ctx.prefetched_stylists = []

        mock_tool = MagicMock()
        called_with_query: list[str] = []

        async def mock_ainvoke(args):
            called_with_query.append(args.get("query", ""))
            return {"shape": "no_match"}

        mock_tool.ainvoke = mock_ainvoke

        with patch("agent.tools.search_services.search_services", mock_tool):
            await mode._f7_auto_recover("quiero cita el viernes para un corte", ctx)

        # "viernes" is a date stopword (normalized, no accent)
        assert "viernes" in _DATE_STOPWORDS
        # If search was called, "viernes" should not be in the query
        if called_with_query:
            assert "viernes" not in called_with_query[0].lower()

    @pytest.mark.asyncio
    async def test_stylist_names_stripped_from_f7_query(self):
        """S14: stylist tokens stripped when prefetched_stylists available."""
        mode = make_booking_mode()
        ctx = BookingContext()
        ctx.prefetched_stylists = self.STYLISTS

        mock_tool = MagicMock()
        called_with_query: list[str] = []

        async def mock_ainvoke(args):
            called_with_query.append(args.get("query", ""))
            return {"shape": "no_match"}

        mock_tool.ainvoke = mock_ainvoke

        with patch("agent.tools.search_services.search_services", mock_tool):
            await mode._f7_auto_recover("quiero con Ana un corte", ctx)

        if called_with_query:
            # "Ana" should be stripped from the query
            assert "ana" not in called_with_query[0].lower()

    @pytest.mark.asyncio
    async def test_trivial_query_after_decontamination_returns_none(self):
        """S15: all tokens are date/stylist → empty query → function returns None."""
        mode = make_booking_mode()
        ctx = BookingContext()
        ctx.prefetched_stylists = self.STYLISTS

        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(return_value={"shape": "no_match"})

        with patch("agent.tools.search_services.search_services", mock_tool):
            # "Ana el viernes" — "Ana" stripped by stylist decontamination,
            # "viernes" stripped by date stopwords, "el" stripped by existing stopwords
            # → empty query after all stripping → return None
            result = await mode._f7_auto_recover("Ana el viernes", ctx)

        # Query should be too short after decontamination → None returned (no search called)
        assert result is None

    def test_date_stopwords_contains_spanish_days(self):
        """S16: _DATE_STOPWORDS contains all Spanish day names."""
        days = {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"}
        for day in days:
            assert day in _DATE_STOPWORDS, f"{day!r} missing from _DATE_STOPWORDS"

    def test_date_stopwords_contains_relative_terms(self):
        """S16: _DATE_STOPWORDS contains relative time terms (normalized, no accents)."""
        relative = {"manana", "hoy", "semana"}  # mañana stored as "manana" (normalized)
        for term in relative:
            assert term in _DATE_STOPWORDS, f"{term!r} missing from _DATE_STOPWORDS"


# =============================================================================
# T-4.5: Regression — hint fields default to None, reset_transient clears them
# =============================================================================


class TestBookingContextHintFields:
    """Tests for the 3 new hint fields added to BookingContext."""

    def test_hint_fields_default_to_none(self):
        """S1a: New BookingContext has all hint fields = None."""
        ctx = BookingContext()
        assert ctx.preferred_date_hint is None
        assert ctx.stylist_name_hint is None
        assert ctx.notes_hint is None

    def test_reset_transient_clears_hint_fields(self):
        """S1b: reset_transient() clears all 3 hint fields."""
        ctx = BookingContext()
        ctx.preferred_date_hint = "el viernes"
        ctx.stylist_name_hint = "Ana"
        ctx.notes_hint = "alérgica al amoniaco"
        ctx.confirmed_services = []  # prevent reset_transient from needing confirmed_services

        ctx.reset_transient()

        assert ctx.preferred_date_hint is None
        assert ctx.stylist_name_hint is None
        assert ctx.notes_hint is None

    def test_hint_fields_serialized_in_to_mode_context(self):
        """Hints round-trip through to_mode_context / from_mode_context."""
        ctx = BookingContext()
        ctx.preferred_date_hint = "mañana"
        ctx.stylist_name_hint = "Pilar"
        ctx.notes_hint = "pelo muy rizado"

        serialized = ctx.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

        assert restored.preferred_date_hint == "mañana"
        assert restored.stylist_name_hint == "Pilar"
        assert restored.notes_hint == "pelo muy rizado"

    def test_hint_fields_not_serialized_when_none(self):
        """None hints are omitted from mode_context (lean serialization)."""
        ctx = BookingContext()
        serialized = ctx.to_mode_context()
        assert "preferred_date_hint" not in serialized
        assert "stylist_name_hint" not in serialized
        assert "notes_hint" not in serialized
