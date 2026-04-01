"""Unit tests for pre-resolver guards (pre-resolver-hardening change).

Coverage (Commit 1 — P1: one-liner guards):
- SC-1: _resolve_audience_hint locked when ctx.service_id is set
- SC-2: _extract_name_from_conversation locked when ctx.customer_id is set
- SC-7 (regression): guards do NOT block when ctx fields are None

Coverage (Commit 2 — P2: context-guard helpers):
- _previous_assistant_presented_slots: True for each detection pattern, False otherwise
- _previous_assistant_presented_stylists: True for numbered stylists + context, False otherwise
- SC-3: _resolve_user_slot_selection blocked when no slots were presented
- SC-4: _detect_addon_acceptance blocked when ctx.offered_slots is non-empty
- SC-5: _try_resolve_stylist_from_message blocked when stylists were not listed
- SC-8 (regression): slot resolver fires when slots WERE shown and user says "2"

Coverage (Commit 3 — P3: confirmation threshold):
- SC-6a: standalone "sí" opens gate
- SC-6b: "sí, pero el tinte también" does NOT open gate
- SC-9a: "perfecto" opens gate
- SC-9b: "perfecto pero quiero el corte de niño" does NOT open gate

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from unittest.mock import MagicMock

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import (
    BookingMode,
    _build_disambiguation_section,
    _detect_addon_acceptance,
    _detect_confirmation_exchange,
    _extract_name_from_conversation,
    _previous_assistant_presented_slots,
    _previous_assistant_presented_stylists,
    _resolve_user_slot_selection,
    _try_resolve_stylist_from_message,
)
from agent.modes.tool_extractors import (
    _resolve_user_candidate_selection,
    _resolve_user_clarification_selection,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_mode() -> BookingMode:
    """Create a BookingMode with a mocked LLM."""
    from unittest.mock import AsyncMock

    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "ok"
    mock_response.tool_calls = []
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return BookingMode(tools=[], llm_client=mock_llm)


def _make_state(messages: list[dict] | None = None) -> dict:
    """Create a minimal ConversationState."""
    return {
        "messages": messages or [],
        "mode_context": {},
        "customer_phone": None,
        "customer_id": None,
        "customer_name": None,
        "customer_first_name": None,
    }


def _assistant_msg(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _user_msg(content: str) -> dict:
    return {"role": "user", "content": content}


# =============================================================================
# Commit 1 — P1: SC-1 — _resolve_audience_hint locked when service_id is set
# =============================================================================


class TestResolveAudienceHintGuard:
    """SC-1: audience hint is NOT overwritten when ctx.service_id is already set."""

    def test_guard_blocks_when_service_id_set(self):
        """SC-1: ctx.service_id set → _resolve_audience_hint returns without modifying ctx."""
        mode = _make_mode()
        ctx = BookingContext(service_id="some-service-uuid", service_audience_hint="adult_female")

        # Build a state where the user message has a different audience keyword
        # "caballero" (singular) is in the audience map and would normally override to adult_male
        state = _make_state(messages=[_user_msg("para caballero")])

        mode._resolve_audience_hint(state, ctx)

        # The hint must remain as it was — NOT overwritten by "caballero"
        assert ctx.service_audience_hint == "adult_female"

    def test_guard_blocks_hint_even_when_hint_was_none(self):
        """SC-1 variant: service_id set + audience_hint=None → still no extraction."""
        mode = _make_mode()
        ctx = BookingContext(service_id="some-service-uuid", service_audience_hint=None)
        state = _make_state(messages=[_user_msg("para caballero")])

        mode._resolve_audience_hint(state, ctx)

        # Guard fires before any extraction — hint stays None
        assert ctx.service_audience_hint is None


# =============================================================================
# Commit 1 — P1: SC-7 (regression) — guard does NOT block when service_id is None
# =============================================================================


class TestResolveAudienceHintRegression:
    """SC-7: guards don't interfere when ctx.service_id is None (happy path)."""

    def test_guard_does_not_block_when_service_id_none(self):
        """SC-7: service_id=None → extraction proceeds normally."""
        mode = _make_mode()
        ctx = BookingContext(service_id=None, service_audience_hint=None)
        # Use "caballero" (singular) — the audience map uses exact singular token matching
        state = _make_state(messages=[_user_msg("para caballero")])

        mode._resolve_audience_hint(state, ctx)

        # Hint should be extracted because guard doesn't block
        assert ctx.service_audience_hint is not None


# =============================================================================
# Commit 1 — P1: SC-2 — _extract_name_from_conversation locked when customer_id set
# =============================================================================


class TestExtractNameGuard:
    """SC-2: name extraction is NOT performed when ctx.customer_id is already set."""

    def test_guard_blocks_when_customer_id_set(self):
        """SC-2: ctx.customer_id set → returns None without modifying ctx.customer_name."""
        ctx = BookingContext(customer_id="some-customer-uuid", customer_name=None)
        state = _make_state()

        _extract_name_from_conversation(state, "me llamo Juan", ctx)

        assert ctx.customer_name is None

    def test_guard_blocks_tier1_pattern(self):
        """SC-2 variant: Tier 1 pattern 'Soy Ana' also blocked by customer_id guard."""
        ctx = BookingContext(customer_id="some-customer-uuid", customer_name=None)
        state = _make_state()

        _extract_name_from_conversation(state, "Soy Ana García", ctx)

        assert ctx.customer_name is None


# =============================================================================
# Commit 1 — P1: SC-7 regression — extraction still works when customer_id is None
# =============================================================================


class TestExtractNameRegression:
    """SC-7: customer_id=None → extraction proceeds normally."""

    def test_extraction_works_when_customer_id_none(self):
        """SC-7 regression: customer_id=None → name can be extracted."""
        ctx = BookingContext(customer_id=None, customer_name=None)
        state = _make_state()

        _extract_name_from_conversation(state, "me llamo María", ctx)

        assert ctx.customer_name == "María"


# =============================================================================
# Commit 2 — P2: _previous_assistant_presented_slots helper tests
# =============================================================================


class TestPreviousAssistantPresentedSlots:
    """Tests for the _previous_assistant_presented_slots helper."""

    def test_returns_true_for_numbered_time_options(self):
        """Numbered time entries like '1. Lunes a las 10:00' → True."""
        messages = [
            _assistant_msg(
                "Aquí tienes los horarios disponibles:\n1. Lunes a las 10:00\n2. Martes a las 11:30"
            ),
        ]
        assert _previous_assistant_presented_slots(messages) is True

    def test_returns_true_for_horarios_keyword(self):
        """Message containing 'horarios' → True."""
        messages = [
            _assistant_msg("Estos son los horarios disponibles para esta semana."),
        ]
        assert _previous_assistant_presented_slots(messages) is True

    def test_returns_true_for_alguno_de_estos_horarios(self):
        """Message containing '¿Alguno de estos horarios' → True."""
        messages = [
            _assistant_msg("¿Alguno de estos horarios te viene bien?"),
        ]
        assert _previous_assistant_presented_slots(messages) is True

    def test_returns_false_for_name_ask(self):
        """Message asking for name → False."""
        messages = [
            _assistant_msg("¿Cuál es tu nombre?"),
        ]
        assert _previous_assistant_presented_slots(messages) is False

    def test_returns_false_for_empty_messages(self):
        """No messages → False."""
        assert _previous_assistant_presented_slots([]) is False

    def test_returns_false_for_no_assistant_message(self):
        """Only user messages → False."""
        messages = [_user_msg("quiero una cita")]
        assert _previous_assistant_presented_slots(messages) is False

    def test_ignores_user_messages_for_check(self):
        """User message with time pattern doesn't count — needs assistant message."""
        messages = [
            _user_msg("a las 10:00"),
        ]
        assert _previous_assistant_presented_slots(messages) is False

    def test_checks_last_assistant_message(self):
        """Only last assistant message is checked."""
        messages = [
            _assistant_msg("¿Alguno de estos horarios te viene bien?"),
            _user_msg("el 2"),
            _assistant_msg("¿Tu nombre?"),  # last assistant message — no slots
        ]
        assert _previous_assistant_presented_slots(messages) is False


# =============================================================================
# Commit 2 — P2: _previous_assistant_presented_stylists helper tests
# =============================================================================


class TestPreviousAssistantPresentedStylists:
    """Tests for the _previous_assistant_presented_stylists helper."""

    def test_returns_true_for_numbered_stylist_list(self):
        """Numbered list with capitalized names + 'con quién' context → True."""
        messages = [
            _assistant_msg("¿Con quién te gustaría la cita?\n1. Ana\n2. Marta\n3. Sofía"),
        ]
        assert _previous_assistant_presented_stylists(messages) is True

    def test_returns_true_for_estilista_with_elije(self):
        """'estilista' + 'elige' in message → True."""
        messages = [
            _assistant_msg("Elige tu estilista preferida:\n1. Laura\n2. Carmen"),
        ]
        assert _previous_assistant_presented_stylists(messages) is True

    def test_returns_false_for_unrelated_message(self):
        """Unrelated assistant message → False."""
        messages = [
            _assistant_msg("¿A qué hora te viene mejor?"),
        ]
        assert _previous_assistant_presented_stylists(messages) is False

    def test_returns_false_for_name_ask(self):
        """Name-asking message → False."""
        messages = [
            _assistant_msg("¿Cuál es tu nombre?"),
        ]
        assert _previous_assistant_presented_stylists(messages) is False

    def test_returns_false_for_empty_messages(self):
        """No messages → False."""
        assert _previous_assistant_presented_stylists([]) is False

    def test_checks_last_assistant_message(self):
        """Only last assistant message is checked."""
        messages = [
            _assistant_msg("¿Con quién te gustaría la cita?\n1. Ana\n2. Marta"),
            _user_msg("Ana"),
            _assistant_msg("¿Cuál es el día que prefieres?"),  # last — no stylists
        ]
        assert _previous_assistant_presented_stylists(messages) is False


# =============================================================================
# Commit 2 — P2: SC-3 — slot resolver blocked without prior slot presentation
# =============================================================================


class TestResolveUserSlotSelectionGuard:
    """SC-3: _resolve_user_slot_selection returns False when slots weren't presented."""

    def test_sc3_blocked_when_no_slot_presentation(self):
        """SC-3: last assistant message didn't show slots → returns False."""
        ctx = BookingContext(
            offered_slots=[
                {
                    "date": "Lunes",
                    "time": "10:00",
                    "full_datetime": "2026-04-06T10:00:00",
                    "stylist_id": "stylist-1",
                    "stylist_name": "Ana",
                },
                {
                    "date": "Martes",
                    "time": "11:00",
                    "full_datetime": "2026-04-07T11:00:00",
                    "stylist_id": "stylist-1",
                    "stylist_name": "Ana",
                },
            ]
        )
        messages = [_assistant_msg("¿Cuál es tu nombre?")]

        result = _resolve_user_slot_selection("el 2", ctx, messages)

        assert result is False
        assert ctx.selected_slot is None

    def test_sc3_passes_when_no_messages_passed(self):
        """Guard is bypassed when messages=None (backward compat fallback)."""
        ctx = BookingContext(
            offered_slots=[
                {
                    "date": "Lunes",
                    "time": "10:00",
                    "full_datetime": "2026-04-06T10:00:00",
                    "stylist_id": "stylist-1",
                    "stylist_name": "Ana",
                },
            ]
        )
        # messages=None means "don't check" — existing behavior preserved
        result = _resolve_user_slot_selection("1", ctx, None)

        assert result is True


# =============================================================================
# Commit 2 — P2: SC-8 (regression) — slot resolver fires when slots WERE shown
# =============================================================================


class TestResolveUserSlotSelectionRegression:
    """SC-8: resolver fires correctly when last assistant DID present slots."""

    def test_sc8_resolves_slot_when_slots_were_shown(self):
        """SC-8: numbered slot list in last assistant message → resolver fires."""
        ctx = BookingContext(
            offered_slots=[
                {
                    "date": "Lunes",
                    "time": "10:00",
                    "full_datetime": "2026-04-06T10:00:00",
                    "stylist_id": "stylist-1",
                    "stylist_name": "Ana",
                },
                {
                    "date": "Martes",
                    "time": "11:00",
                    "full_datetime": "2026-04-07T11:00:00",
                    "stylist_id": "stylist-2",
                    "stylist_name": "Marta",
                },
                {
                    "date": "Miércoles",
                    "time": "12:00",
                    "full_datetime": "2026-04-08T12:00:00",
                    "stylist_id": "stylist-1",
                    "stylist_name": "Ana",
                },
                {
                    "date": "Jueves",
                    "time": "13:00",
                    "full_datetime": "2026-04-09T13:00:00",
                    "stylist_id": "stylist-3",
                    "stylist_name": "Sofía",
                },
            ]
        )
        messages = [
            _assistant_msg(
                "¿Alguno de estos horarios te viene bien?\n"
                "1. Lunes a las 10:00\n"
                "2. Martes a las 11:00\n"
                "3. Miércoles a las 12:00\n"
                "4. Jueves a las 13:00"
            )
        ]

        result = _resolve_user_slot_selection("2", ctx, messages)

        assert result is True
        assert ctx.selected_slot is not None
        assert ctx.selected_slot["time"] == "11:00"


# =============================================================================
# Commit 2 — P2: SC-4 — addon detector blocked when ctx.offered_slots non-empty
# =============================================================================


class TestDetectAddonAcceptanceGuard:
    """SC-4: _detect_addon_acceptance returns None when ctx.offered_slots is non-empty."""

    def test_sc4_blocked_when_offered_slots_present(self):
        """SC-4: offered_slots non-empty → _detect_addon_acceptance returns None."""
        ctx = BookingContext(
            pending_recommendations=["Tinte"],
            recommendations_shown=True,
            offered_slots=[
                {"date": "Lunes", "time": "10:00", "stylist_id": "s-1", "stylist_name": "Ana"},
            ],
        )

        result = _detect_addon_acceptance("también quiero el tinte", ctx)

        assert result is None

    def test_sc4_fires_when_offered_slots_empty(self):
        """SC-4 regression: offered_slots=None → addon detector fires normally."""
        ctx = BookingContext(
            pending_recommendations=["Tinte"],
            recommendations_shown=True,
            offered_slots=None,
        )

        result = _detect_addon_acceptance("también quiero el tinte", ctx)

        assert result == "Tinte"


# =============================================================================
# Commit 2 — P2: SC-5 — stylist resolver blocked when stylists not listed
# =============================================================================


class TestTryResolveStylistGuard:
    """SC-5: _try_resolve_stylist_from_message skips when stylists weren't shown."""

    def test_sc5_blocked_when_no_stylist_presentation(self):
        """SC-5: last assistant message didn't list stylists → stylist_id stays None."""
        ctx = BookingContext(
            stylist_id=None,
            prefetched_stylists=[
                {"id": "stylist-1", "name": "Laura"},
                {"id": "stylist-2", "name": "Sofía"},
            ],
        )
        messages = [_assistant_msg("¿Cuándo quieres la cita?")]

        _try_resolve_stylist_from_message("quiero con Laura", ctx, messages)

        assert ctx.stylist_id is None

    def test_sc5_fires_when_stylists_were_listed(self):
        """SC-5 regression: stylists listed in last message → resolver fires."""
        ctx = BookingContext(
            stylist_id=None,
            prefetched_stylists=[
                {"id": "stylist-1", "name": "Laura"},
                {"id": "stylist-2", "name": "Sofía"},
            ],
        )
        messages = [
            _assistant_msg("¿Con quién te gustaría la cita?\n1. Laura\n2. Sofía"),
        ]

        _try_resolve_stylist_from_message("quiero con Laura", ctx, messages)

        assert ctx.stylist_id == "stylist-1"
        assert ctx.stylist_name == "Laura"

    def test_sc5_bypassed_when_messages_none(self):
        """Guard is bypassed when messages=None (backward compat fallback)."""
        ctx = BookingContext(
            stylist_id=None,
            prefetched_stylists=[
                {"id": "stylist-1", "name": "Laura"},
            ],
        )

        _try_resolve_stylist_from_message("quiero con Laura", ctx, None)

        assert ctx.stylist_id == "stylist-1"


# =============================================================================
# Commit 3 — P3: SC-6a/SC-6b — confirmation threshold
# =============================================================================


def _make_confirmation_state(
    user_content: str, booking_complete: bool = True
) -> tuple[dict, BookingContext]:
    """Create state + ctx for confirmation exchange tests."""
    ctx = BookingContext(
        confirmation_summary_sent=True,
        # Booking data required by _is_booking_data_complete
        customer_name="Ana" if booking_complete else None,
        customer_id="cust-1" if booking_complete else None,
        selected_services=["Corte Dama"] if booking_complete else [],
        offered_slots=[
            {"date": "Lunes", "time": "10:00", "stylist_id": "s-1", "stylist_name": "Ana"}
        ]
        if booking_complete
        else None,
        selected_slot={
            "date": "Lunes",
            "time": "10:00",
            "full_datetime": "2026-04-06T10:00:00",
            "stylist_id": "s-1",
            "stylist_name": "Ana",
        }
        if booking_complete
        else None,
        stylist_id="s-1" if booking_complete else None,
        stylist_name="Ana" if booking_complete else None,
    )
    state = _make_state(
        messages=[
            _assistant_msg("Tu reserva sería el Lunes a las 10:00 con Ana. ¿Confirmamos?"),
            _user_msg(user_content),
        ]
    )
    return state, ctx


class TestDetectConfirmationExchangeThreshold:
    """Confirmation threshold guard: only standalone affirmatives open the gate."""

    def test_sc6a_standalone_si_opens_gate(self):
        """SC-6a: standalone 'sí' → confirmation_shown = True."""
        state, ctx = _make_confirmation_state("sí")

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_sc6b_compound_si_does_not_open_gate(self):
        """SC-6b: 'sí, pero el tinte también' (>3 tokens) → gate NOT opened."""
        state, ctx = _make_confirmation_state("sí, pero el tinte también")

        _detect_confirmation_exchange(state, ctx)

        assert not ctx.confirmation_shown

    def test_sc9a_perfecto_opens_gate(self):
        """SC-9a: 'perfecto' (standalone affirmative) → confirmation_shown = True."""
        state, ctx = _make_confirmation_state("perfecto")

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_sc9b_compound_perfecto_does_not_open_gate(self):
        """SC-9b: 'perfecto pero quiero el corte de niño' (>3 tokens) → gate NOT opened."""
        state, ctx = _make_confirmation_state("perfecto pero quiero el corte de niño")

        _detect_confirmation_exchange(state, ctx)

        assert not ctx.confirmation_shown

    def test_dale_opens_gate(self):
        """'dale' (1 token) → confirmation_shown = True."""
        state, ctx = _make_confirmation_state("dale")

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_de_acuerdo_opens_gate(self):
        """'de acuerdo' (2 tokens) → confirmation_shown = True."""
        state, ctx = _make_confirmation_state("de acuerdo")

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_por_supuesto_opens_gate(self):
        """'por supuesto' (2 tokens) → confirmation_shown = True."""
        state, ctx = _make_confirmation_state("por supuesto")

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_si_pero_compound_blocked(self):
        """'sí pero quiero cambiar la hora' (>3 tokens) → gate NOT opened."""
        state, ctx = _make_confirmation_state("sí pero quiero cambiar la hora")

        _detect_confirmation_exchange(state, ctx)

        assert not ctx.confirmation_shown


# =============================================================================
# Clarification loop fix — T5.2 integration
# =============================================================================


def _make_clarification_ctx_with_options() -> BookingContext:
    """Return a BookingContext with audience clarification pending."""
    options = [
        {
            "service_id": f"svc-{i}",
            "service_name": f"Corte {i}",
            "label": f"Opción {i}",
            "value": f"opcion_{i}",
            "category": "peluqueria",
            "duration_minutes": 30,
            "family": None,
        }
        for i in range(1, 6)
    ]
    ctx = BookingContext()
    ctx.pending_clarifications = [{"axis": "audience", "options": options}]
    return ctx


def _clarification_assistant_messages() -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": (
                "¿El corte es para...?\n"
                "1. Opción 1\n2. Opción 2\n3. Opción 3\n4. Opción 4\n5. Opción 5"
            ),
        }
    ]


class TestClarificationLoopFix:
    """Integration scenario: pre-resolver → context build chain (T5.2)."""

    def test_clarification_resolved_before_context_build(self):
        """Turn sequence: user sends '4' → resolver fires → pending cleared → no <clarification>.

        Simulates the pre-resolver + _build_dynamic_context pipeline:
        1. Construct ctx with pending_clarifications
        2. Call _resolve_user_clarification_selection with '4'
        3. Assert pending_clarifications == [] and service_id set
        4. Call _build_disambiguation_section and assert '<clarification>' block absent
        """
        ctx = _make_clarification_ctx_with_options()
        messages = _clarification_assistant_messages()

        resolved = _resolve_user_clarification_selection("4", ctx, messages)

        assert resolved is True
        assert ctx.service_id == "svc-4"
        assert ctx.pending_clarifications == []

        # After resolution, disambiguation section must be empty
        disambiguation = _build_disambiguation_section(ctx)
        assert "<clarification>" not in disambiguation
        assert "CLARIFICACIÓN PENDIENTE" not in disambiguation

    def test_unresolved_clarification_keeps_context_block(self):
        """When resolver returns False (no match), clarification block persists."""
        ctx = _make_clarification_ctx_with_options()
        messages = _clarification_assistant_messages()

        resolved = _resolve_user_clarification_selection("hola", ctx, messages)

        assert resolved is False
        assert len(ctx.pending_clarifications) == 1

        # Disambiguation section should still contain the options
        disambiguation = _build_disambiguation_section(ctx)
        assert disambiguation  # non-empty — LLM will re-present the list


# =============================================================================
# Candidate Services Resolver Integration Tests
# =============================================================================


def _make_candidate_services() -> list[dict]:
    """Three candidate services matching what search_services Shape-3 returns."""
    return [
        {
            "id": "svc-1",
            "name": "Corte Dama",
            "duration_minutes": 45,
            "category": "peluqueria",
            "description": "Corte y secado para dama",
        },
        {
            "id": "svc-2",
            "name": "Bioterapia Capilar",
            "duration_minutes": 60,
            "category": "peluqueria",
            "description": "Tratamiento nutritivo intensivo",
        },
        {
            "id": "svc-3",
            "name": "Tinte Completo",
            "duration_minutes": 90,
            "category": "coloracion",
            "description": "Coloración completa con amoniaco",
        },
    ]


def _candidate_assistant_messages() -> list[dict]:
    """Simulate the assistant listing all three candidate services."""
    return [
        {"role": "user", "content": "quiero un servicio de pelo"},
        {
            "role": "assistant",
            "content": (
                "Encontré varias opciones que pueden interesarte:\n"
                "1. Corte Dama\n"
                "2. Bioterapia Capilar\n"
                "3. Tinte Completo\n"
                "¿Cuál de estas opciones te gustaría?"
            ),
        },
    ]


class TestCandidateServicesResolver:
    """Integration scenario: candidate pre-resolver → context build chain (T6)."""

    def test_candidate_resolved_before_context_build(self):
        """Full 2-turn sequence: candidates presented → user selects '2' → resolved + cleared.

        Simulates the pre-resolver + context pipeline:
        1. Construct ctx with candidate_services populated
        2. Provide messages where last assistant lists all candidate names
        3. Call _resolve_user_candidate_selection with '2'
        4. Assert True returned + service_id set to candidate[1].id + candidate_services == []
        """
        ctx = BookingContext()
        ctx.candidate_services = _make_candidate_services()
        messages = _candidate_assistant_messages()

        resolved = _resolve_user_candidate_selection("2", ctx, messages)

        assert resolved is True
        assert ctx.service_id == "svc-2"
        assert ctx.service_name == "Bioterapia Capilar"
        assert ctx.candidate_services == []
        # service_duration_minutes should be propagated from the candidate dict
        assert ctx.service_duration_minutes == 60

    def test_candidate_resolved_by_name(self):
        """User types partial service name → resolves via substring match."""
        ctx = BookingContext()
        ctx.candidate_services = _make_candidate_services()
        messages = _candidate_assistant_messages()

        resolved = _resolve_user_candidate_selection("tinte completo", ctx, messages)

        assert resolved is True
        assert ctx.service_id == "svc-3"
        assert ctx.service_name == "Tinte Completo"
        assert ctx.candidate_services == []

    def test_unresolved_candidate_keeps_candidate_services(self):
        """When resolver returns False, candidate_services remains populated."""
        ctx = BookingContext()
        ctx.candidate_services = _make_candidate_services()
        messages = _candidate_assistant_messages()

        resolved = _resolve_user_candidate_selection("no sé cuál elegir", ctx, messages)

        assert resolved is False
        assert ctx.service_id is None
        assert len(ctx.candidate_services) == 3
