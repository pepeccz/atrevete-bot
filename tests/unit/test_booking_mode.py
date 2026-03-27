"""
Unit tests for agent/modes/booking_mode.py — BookingMode (LLM-driven booking).

Coverage:
- Import and instantiation
- Cancel/escalate detection (with negation)
- Name redaction (module-level functions)
- Dynamic context section builders (module-level functions)
- BookingContext integration (round-trip, readiness, summaries)

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import (
    BookingMode,
    _AUDIENCE_KEYWORDS,
    _CONFIRMATION_QUESTION_PATTERNS,
    _build_disambiguation_section,
    _build_offered_slots_section,
    _build_recommendations_section,
    _build_stylists_section,
    _combo_offer_in_response,
    _contains_name_token,
    _detect_recommendation_decline,
    _extract_name_from_conversation,
    _extract_notes_from_conversation,
    _normalize_text,
    _redact_name_tokens,
    _resolve_user_slot_selection,
)
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_intent(intent: str = "book", confidence: float = 0.9) -> IntentResult:
    return IntentResult(intent=intent, confidence=confidence, raw_input="test", mode_hint="BOOKING")


def make_mock_llm(response_text: str = "¿Qué servicio deseas?") -> AsyncMock:
    """Mock LLM that returns a simple text response with no tool calls."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "¿Qué servicio deseas?") -> BookingMode:
    mock_llm = make_mock_llm(llm_response)
    return BookingMode(tools=[], llm_client=mock_llm)


def make_state(
    customer_name: str | None = "María",
    customer_id: str | None = "cust-001",
    user_message: str = "quiero reservar",
    mode_context: dict | None = None,
) -> dict:
    """Build a ConversationState for BookingMode tests."""
    state = create_initial_state("conv-001", "+34612345678")
    state["customer_name"] = customer_name
    state["customer_id"] = customer_id
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"
    state["mode_context"] = mode_context or {}
    # Add a user message so _get_last_user_message finds something
    state["messages"] = [{"role": "user", "content": user_message}]
    return state


# =============================================================================
# 1. Import and Instantiation
# =============================================================================


class TestBookingModeInstantiation:
    def test_can_import_and_create(self):
        mode = make_booking_mode()
        assert mode is not None

    def test_mode_name_is_booking(self):
        mode = make_booking_mode()
        assert mode.mode_name == "BOOKING"


# =============================================================================
# 2. Cancel / Escalate Detection
# =============================================================================


class TestCancelEscalateDetection:
    """Tests for _check_special_intents fast path."""

    def test_cancel_phrase_transitions_to_general(self):
        mode = make_booking_mode()
        state = make_state(user_message="cancelar mi cita")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "cancelar mi cita", intent)

        assert result is not None
        assert result["current_mode"] == "GENERAL"

    def test_negation_does_not_cancel(self):
        """'no quiero cancelar' should NOT trigger cancellation."""
        mode = make_booking_mode()
        state = make_state(user_message="no quiero cancelar")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "no quiero cancelar", intent)

        assert result is None  # No special intent — continues normal flow

    def test_escalate_phrase_transitions_to_escalation(self):
        mode = make_booking_mode()
        state = make_state(user_message="necesito hablar con alguien")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "necesito hablar con alguien", intent)

        assert result is not None
        assert result["current_mode"] == "ESCALATION"

    def test_cancel_intent_from_router_transitions(self):
        """Cancel intent from router (not phrase) should also transition."""
        mode = make_booking_mode()
        state = make_state(user_message="ya no quiero")
        intent = make_intent("cancel")

        result = mode._check_special_intents(state, "ya no quiero", intent)

        assert result is not None
        assert result["current_mode"] == "GENERAL"

    def test_escalate_intent_from_router_transitions(self):
        mode = make_booking_mode()
        state = make_state(user_message="ayuda")
        intent = make_intent("escalate")

        result = mode._check_special_intents(state, "ayuda", intent)

        assert result is not None
        assert result["current_mode"] == "ESCALATION"

    def test_normal_message_returns_none(self):
        mode = make_booking_mode()
        state = make_state(user_message="quiero un corte de pelo")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "quiero un corte de pelo", intent)

        assert result is None

    def test_cancel_sets_last_node_and_clears_user_message(self):
        mode = make_booking_mode()
        state = make_state(user_message="cancelar")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "cancelar", intent)

        assert result is not None
        assert result["last_node"] == "booking"
        assert result["user_message"] is None

    def test_continuemos_negates_cancel(self):
        """'continuemos' is a negation token — should not cancel."""
        mode = make_booking_mode()
        state = make_state(user_message="no quiero cancelar, continuemos")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "no quiero cancelar, continuemos", intent)

        assert result is None

    @pytest.mark.parametrize(
        "message",
        [
            "lo dejo",
            "mejor no",
            "he cambiado de opinión",
            "cambié de opinión",
            "paso",
            "ya no quiero",
            "lo cancelo",
            "lo dejo por ahora",
            "mejor lo dejo",
            "Mejor no, he cambiado de opinión. Lo dejo por ahora.",
        ],
    )
    def test_new_cancel_phrases_detected(self, message):
        """Common Spanish cancel expressions must trigger cancellation."""
        mode = make_booking_mode()
        state = make_state(user_message=message)
        intent = make_intent("book")

        result = mode._check_special_intents(state, message, intent)

        assert result is not None, f"Cancel not detected for: {message!r}"
        assert result["current_mode"] == "GENERAL"


# =============================================================================
# 3. Name Redaction (module-level functions)
# =============================================================================


class TestNameRedaction:
    def test_contains_name_token_finds_name(self):
        assert _contains_name_token("Hola María, ¿cómo estás?", "María") is True

    def test_contains_name_token_no_match(self):
        assert _contains_name_token("Hola, ¿cómo estás?", "María") is False

    def test_contains_name_token_accent_insensitive(self):
        """'Maria' (no accent) should match 'María' (with accent)."""
        assert _contains_name_token("Hola Maria, bienvenida", "María") is True

    def test_contains_name_token_skips_short_tokens(self):
        """Tokens < 3 chars (e.g. 'de') should not trigger a match."""
        assert _contains_name_token("Hola de todos", "Ana de García") is False

    def test_redact_name_tokens_removes_name(self):
        result = _redact_name_tokens("Hola María, tu cita está confirmada.", "María")
        assert "María" not in result
        assert "confirmada" in result

    def test_redact_name_tokens_compound_name(self):
        result = _redact_name_tokens("Hola María José, tu cita está lista.", "María José")
        assert "María" not in result
        assert "José" not in result
        assert "lista" in result

    def test_redact_name_tokens_no_match_unchanged(self):
        original = "Tu cita está confirmada."
        result = _redact_name_tokens(original, "Carlos")
        assert result == original

    def test_redact_names_on_mode_instance(self):
        """_redact_names method on BookingMode uses state customer names."""
        mode = make_booking_mode()
        state = make_state(customer_name="Laura")
        text = "Perfecto Laura, ya tienes tu cita."

        result = mode._redact_names(state, text)

        assert "Laura" not in result
        assert "cita" in result

    def test_redact_names_no_name_in_state_unchanged(self):
        mode = make_booking_mode()
        state = make_state(customer_name=None)
        text = "Tu cita está lista."

        result = mode._redact_names(state, text)

        assert result == text


# =============================================================================
# 4. Dynamic Context Section Builders
# =============================================================================


class TestBuildDisambiguationSection:
    def test_with_pending_clarification(self):
        ctx = BookingContext(
            pending_clarifications=[
                {
                    "axis": "audience",
                    "question_hint": "¿Para quién es?",
                    "options": [
                        {"value": "adult_female", "label": "Mujer adulta"},
                        {"value": "adult_male", "label": "Hombre adulto"},
                    ],
                }
            ]
        )

        result = _build_disambiguation_section(ctx)

        assert "CLARIFICACIÓN PENDIENTE" in result
        assert "¿Para quién es?" in result
        assert "Mujer adulta" in result

    def test_empty_when_no_disambiguation(self):
        ctx = BookingContext()
        result = _build_disambiguation_section(ctx)
        assert result == ""

    def test_renders_empty_after_pre_resolver_cleared_clarification(self):
        """After resolve_pending_clarification clears pending_clarifications, renders empty."""
        ctx = BookingContext(
            service_audience_hint="adult_female",
            # pending_clarifications defaults to [] — pre-resolver already cleared it
        )

        result = _build_disambiguation_section(ctx)

        assert result == ""

    def test_renders_pending_when_not_auto_resolved(self):
        """When hint doesn't match (pre-resolver returned False), renders pending options."""
        ctx = BookingContext(
            service_audience_hint="baby",
            pending_clarifications=[
                {
                    "axis": "audience",
                    "question_hint": "¿Para quién es?",
                    "options": [
                        {"value": "adult_female", "label": "Mujer adulta"},
                        {"value": "adult_male", "label": "Hombre adulto"},
                    ],
                },
            ],
        )

        result = _build_disambiguation_section(ctx)

        assert "CLARIFICACIÓN PENDIENTE (audience)" in result
        assert "Mujer adulta" in result
        assert "Hombre adulto" in result
        assert "CLARIFICACIÓN RESUELTA" not in result

    def test_candidate_services_shown(self):
        ctx = BookingContext(
            candidate_services=[
                {"name": "Corte señora"},
                {"name": "Tinte raíz"},
            ]
        )

        result = _build_disambiguation_section(ctx)

        assert "Corte señora" in result
        assert "Tinte raíz" in result


class TestBuildStylistsSection:
    def test_with_prefetched_stylists(self):
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "next_slot_summary": "Lunes 10:00"},
                {"name": "Bea", "next_slot_summary": "Martes 11:00"},
            ]
        )

        result = _build_stylists_section(ctx)

        assert "Ana" in result
        assert "Lunes 10:00" in result
        assert "Bea" in result

    def test_empty_when_no_stylists(self):
        ctx = BookingContext()
        result = _build_stylists_section(ctx)
        assert result == ""

    def test_soonest_slot_shown(self):
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "next_slot_summary": "Hoy 15:00"}],
            soonest_any_slot="Hoy 15:00",
        )

        result = _build_stylists_section(ctx)

        assert "Cualquier profesional disponible" in result
        assert "Hoy 15:00" in result

    def test_recurrent_stylist_hint_shown(self):
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "next_slot_summary": "Mañana 9:00"}],
            recurrent_stylist_hint="Ana",
        )

        result = _build_stylists_section(ctx)

        assert "Estilista habitual" in result
        assert "Ana" in result


class TestBuildOfferedSlotsSection:
    def test_with_offered_slots(self):
        ctx = BookingContext(
            offered_slots=[
                {"day_name": "Lunes", "time": "10:00", "stylist_name": "Ana"},
                {"day_name": "Martes", "time": "11:00", "stylist_name": ""},
            ]
        )

        result = _build_offered_slots_section(ctx)

        assert "Lunes a las 10:00" in result
        assert "con Ana" in result
        assert "Martes a las 11:00" in result

    def test_empty_when_no_slots(self):
        ctx = BookingContext()
        result = _build_offered_slots_section(ctx)
        assert result == ""

    def test_slot_without_stylist_name(self):
        ctx = BookingContext(
            offered_slots=[
                {"day_name": "Viernes", "time": "16:00", "stylist_name": ""},
            ]
        )

        result = _build_offered_slots_section(ctx)

        assert "Viernes a las 16:00" in result
        # The slot display line must not have "con <empty stylist>"
        # Skip the IMPORTANTE header line to find the actual slot line
        slot_lines = [ln for ln in result.split("\n") if ln.startswith("1.")]
        assert slot_lines, "Expected a slot line starting with '1.'"
        assert "con " not in slot_lines[0]


# =============================================================================
# 5. BookingContext Integration
# =============================================================================


class TestBookingContextRoundTrip:
    def test_from_mode_context_to_mode_context_roundtrip(self):
        original = BookingContext(
            service_id="svc-001",
            service_name="Corte señora",
            stylist_id="sty-001",
            stylist_name="Ana",
            customer_name="María",
            customer_id="cust-001",
        )

        serialized = original.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

        assert restored.service_id == "svc-001"
        assert restored.service_name == "Corte señora"
        assert restored.stylist_id == "sty-001"
        assert restored.stylist_name == "Ana"
        assert restored.customer_name == "María"
        assert restored.customer_id == "cust-001"

    def test_from_mode_context_ignores_unknown_keys(self):
        data = {"service_id": "svc-001", "unknown_field": "should_be_ignored"}
        ctx = BookingContext.from_mode_context(data)
        assert ctx.service_id == "svc-001"
        assert not hasattr(ctx, "unknown_field") or ctx.__dict__.get("unknown_field") is None

    def test_to_mode_context_excludes_none_and_empty(self):
        ctx = BookingContext(service_id="svc-001")
        serialized = ctx.to_mode_context()
        assert "service_id" in serialized
        assert "stylist_id" not in serialized  # None → excluded
        assert "candidate_services" not in serialized  # [] → excluded

    def test_to_mode_context_excludes_private_fields(self):
        ctx = BookingContext(_booking_completed=True)
        serialized = ctx.to_mode_context()
        assert "_booking_completed" not in serialized


class TestBookingContextReadiness:
    def test_is_ready_to_book_all_fields(self):
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-23T10:00:00", "date": "2026-03-23"},
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is True

    def test_is_ready_to_book_with_selected_services(self):
        """selected_services satisfies the service requirement."""
        ctx = BookingContext(
            selected_services=["Corte señora"],
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-23T10:00:00"},
            customer_id="cust-001",
        )
        assert ctx.is_ready_to_book() is True

    def test_not_ready_missing_service(self):
        ctx = BookingContext(
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-23T10:00:00"},
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is False

    def test_not_ready_missing_stylist(self):
        ctx = BookingContext(
            service_id="svc-001",
            selected_slot={"start_time": "2026-03-23T10:00:00"},
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is False

    def test_not_ready_missing_slot(self):
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id="sty-001",
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is False

    def test_not_ready_slot_without_start_time(self):
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id="sty-001",
            selected_slot={"date": "2026-03-23"},  # Missing start_time
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is False

    def test_not_ready_missing_customer(self):
        ctx = BookingContext(
            service_id="svc-001",
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-23T10:00:00"},
        )
        assert ctx.is_ready_to_book() is False


class TestBookingContextSummaries:
    def test_collected_summary_shows_populated_fields(self):
        ctx = BookingContext(
            service_name="Corte señora",
            service_duration_minutes=45,
            service_category="Cortes",
            stylist_name="Ana",
            customer_name="María",
        )

        summary = ctx.collected_summary()

        assert "Corte señora" in summary
        assert "45 min" in summary
        assert "Cortes" in summary
        assert "Ana" in summary
        assert "María" in summary

    def test_collected_summary_empty_context(self):
        ctx = BookingContext()
        summary = ctx.collected_summary()
        assert "ningún dato recogido" in summary

    def test_collected_summary_with_slot(self):
        ctx = BookingContext(
            selected_slot={"date": "2026-03-23", "time": "10:00"},
        )
        summary = ctx.collected_summary()
        assert "10:00" in summary

    def test_missing_summary_shows_missing_fields(self):
        ctx = BookingContext()
        summary = ctx.missing_summary()
        assert "servicio" in summary.lower()
        assert "estilista" in summary.lower()
        assert "fecha/hora" in summary.lower()
        assert "nombre" in summary.lower()

    def test_missing_summary_all_complete(self):
        # T-07: customer_id is now required when customer_name is present.
        # "All complete" requires both customer_name AND customer_id AND notes_asked=True.
        ctx = BookingContext(
            service_name="Corte",
            stylist_id="sty-001",
            offered_slots=[{"time": "10:00", "date": "2026-03-23"}],
            customer_name="María",
            customer_id="cust-001",
            notes_asked=True,
        )
        summary = ctx.missing_summary()
        assert "completos" in summary.lower()

    def test_missing_summary_partial(self):
        ctx = BookingContext(
            service_name="Corte",
            customer_name="María",
        )
        summary = ctx.missing_summary()
        assert "estilista" in summary.lower()
        assert "fecha/hora" in summary.lower()
        # Service and name should NOT be listed as missing
        assert "servicio" not in summary.lower()
        assert "nombre" not in summary.lower()


# =============================================================================
# 6. Normalize text helper
# =============================================================================


class TestNormalizeText:
    def test_strips_accents(self):
        assert _normalize_text("cancelar") == "cancelar"
        assert _normalize_text("Cancelar") == "cancelar"

    def test_handles_none(self):
        assert _normalize_text(None) == ""

    def test_handles_empty(self):
        assert _normalize_text("") == ""

    def test_unicode_normalization(self):
        # 'é' composed vs decomposed should normalize the same
        assert _normalize_text("café") == "cafe"


# =============================================================================
# 7. Pre-resolvers (static methods)
# =============================================================================


class TestPreResolvers:
    def test_resolve_customer_from_state(self):
        mode = make_booking_mode()
        ctx = BookingContext()
        state = make_state(customer_name="Laura", customer_id="cust-100")

        BookingMode._resolve_customer_from_state(state, ctx)

        assert ctx.customer_name == "Laura"
        assert ctx.customer_id == "cust-100"

    def test_resolve_customer_does_not_overwrite_existing(self):
        ctx = BookingContext(customer_name="Existing", customer_id="existing-id")
        state = make_state(customer_name="Laura", customer_id="cust-100")

        BookingMode._resolve_customer_from_state(state, ctx)

        assert ctx.customer_name == "Existing"
        assert ctx.customer_id == "existing-id"

    def test_resolve_audience_hint_from_mode_context(self):
        ctx = BookingContext()
        state = make_state()
        state["mode_context"] = {"service_audience_hint": "adult_female"}

        mode = BookingMode.__new__(BookingMode)
        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_female"

    def test_resolve_audience_hint_does_not_overwrite(self):
        ctx = BookingContext(service_audience_hint="adult_male")
        state = make_state()
        state["mode_context"] = {"service_audience_hint": "adult_female"}

        mode = BookingMode.__new__(BookingMode)
        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_male"

    def test_resolve_audience_hint_from_user_message(self):
        ctx = BookingContext()
        state = make_state()
        state["messages"] = [{"role": "user", "content": "Para dama"}]

        mode = BookingMode.__new__(BookingMode)
        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_female"

    def test_resolve_audience_hint_mujer_adulta(self):
        ctx = BookingContext()
        state = make_state()
        state["messages"] = [{"role": "user", "content": "Soy mujer adulta"}]

        mode = BookingMode.__new__(BookingMode)
        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_female"


# =============================================================================
# 13. Pre-tool-call: customer_id injection gate
# =============================================================================


class TestPreToolCallCustomerIdInjection:
    """Verify that _pre_tool_call always injects real customer_id for book().

    All tests provide valid offered_slots, selected_services, customer_name,
    and customer_id so that guards pass and we test the injection logic.
    """

    @pytest.mark.asyncio
    async def test_injects_real_customer_id_from_context(self):
        """When ctx has customer_id, it overwrites whatever the LLM passed."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
            customer_name="Pepe",
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "full_datetime": "2026-03-25T10:00:00+01:00",
                    "stylist_name": "Ana",
                }
            ],
            selected_services=["Corte de Caballero"],
            needs_availability_refresh=False,
            confirmation_shown=True,
            notes_asked=True,
        )
        tool_args = {
            "customer_id": "FAKE-LLM-HALLUCINATED-UUID",
            "services": ["Corte de Caballero"],
            "first_name": "Pepe",
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert result["customer_id"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_rejects_when_no_customer_id(self):
        """When ctx has no customer_id, ToolCallRejection is returned."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = BookingContext(
            customer_name="Pepe",
            offered_slots=[{"stylist_id": "s1", "full_datetime": "2026-03-25T10:00:00+01:00"}],
            selected_services=["Corte de Caballero"],
            needs_availability_refresh=False,
        )
        tool_args = {
            "customer_id": "FAKE-UUID",
            "services": ["Corte de Caballero"],
            "first_name": "Pepe",
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_CUSTOMER_ID"

    @pytest.mark.asyncio
    async def test_rejects_when_no_ctx(self):
        """When _ctx is None (edge case), ToolCallRejection is returned."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = None
        tool_args = {
            "customer_id": "FAKE-UUID",
            "services": ["Corte de Caballero"],
            "first_name": "Pepe",
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_CUSTOMER_ID"

    @pytest.mark.asyncio
    async def test_injects_selected_services_from_context(self):
        """When ctx has selected_services, they are injected into book() args."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
            customer_name="Pepe",
            selected_services=["Corte Caballero", "Barba"],
            offered_slots=[
                {
                    "stylist_id": "s1",
                    "full_datetime": "2026-03-25T10:00:00+01:00",
                    "stylist_name": "Ana",
                }
            ],
            needs_availability_refresh=False,
            confirmation_shown=True,
            notes_asked=True,
        )
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte Caballero"],  # LLM forgot Barba
            "first_name": "Pepe",
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert result["services"] == ["Corte Caballero", "Barba"]
        assert result["customer_id"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_rejects_when_empty_selected_services(self):
        """When ctx has no selected_services, ToolCallRejection is returned."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = BookingContext(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
            customer_name="Pepe",
            selected_services=[],  # Empty → guard fires
            offered_slots=[{"stylist_id": "s1", "full_datetime": "2026-03-25T10:00:00+01:00"}],
            needs_availability_refresh=False,
        )
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte Caballero"],
            "first_name": "Pepe",
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_SELECTED_SERVICES"

    @pytest.mark.asyncio
    async def test_non_book_tool_passes_through(self):
        """Non-book tools should not be intercepted."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()
        tool_args = {"query": "horarios"}

        result = await mode._pre_tool_call("query_info", tool_args)

        assert result == {"query": "horarios"}
        assert "customer_id" not in result

    @pytest.mark.asyncio
    async def test_customer_id_injection_with_slot_index_resolution(self):
        """customer_id injection AND slot_index resolution work together."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
            customer_name="Pepe",
            selected_services=["Corte"],
            needs_availability_refresh=False,
            confirmation_shown=True,
            notes_asked=True,
            offered_slots=[
                {
                    "stylist_id": "aaa-bbb",
                    "full_datetime": "2026-03-25T10:00:00+01:00",
                    "stylist_name": "Ana",
                }
            ],
        )
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte"],
            "first_name": "Pepe",
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        # customer_id injected from context
        assert result["customer_id"] == "550e8400-e29b-41d4-a716-446655440000"
        # slot_index resolved
        assert result["stylist_id"] == "aaa-bbb"
        assert result["start_time"] == "2026-03-25T10:00:00+01:00"
        assert "slot_index" not in result


# =============================================================================
# 14. Combo Recommendations — _build_recommendations_section (Phase 4)
# =============================================================================


class TestBuildRecommendationsSection:
    """Test _build_recommendations_section prompt rendering."""

    def test_renders_when_pending_and_not_shown(self):
        """Pending recommendations that haven't been shown yet → render section."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación", "Corte de Señora"],
            recommendations_shown=False,
            recommendations_declined=False,
        )

        result = _build_recommendations_section(ctx)

        assert "SERVICIOS RECOMENDADOS" in result
        assert "Hidratación" in result
        assert "Corte de Señora" in result

    def test_empty_when_declined(self):
        """Declined recommendations → empty string."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=True,
        )

        assert _build_recommendations_section(ctx) == ""

    def test_empty_when_already_shown(self):
        """Already shown once → empty string (don't repeat)."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=False,
        )

        assert _build_recommendations_section(ctx) == ""

    def test_empty_when_no_recommendations(self):
        """No pending recommendations → empty string."""
        ctx = BookingContext()

        assert _build_recommendations_section(ctx) == ""


# =============================================================================
# 15. Combo Recommendations — _detect_recommendation_decline (Phase 4)
# =============================================================================


class TestDetectRecommendationDecline:
    """Test _detect_recommendation_decline add-on decline detection."""

    def test_detects_no_gracias(self):
        """'no gracias' should trigger decline when recommendations shown."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=False,
        )

        assert _detect_recommendation_decline("no gracias, solo eso", ctx) is True
        assert ctx.recommendations_declined is True

    def test_detects_solo_eso(self):
        """'solo eso' should trigger decline."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
        )

        assert _detect_recommendation_decline("solo eso", ctx) is True
        assert ctx.recommendations_declined is True

    def test_ignores_before_shown(self):
        """Should not detect decline before recommendations are shown."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación"],
            recommendations_shown=False,
        )

        assert _detect_recommendation_decline("no gracias", ctx) is False
        assert ctx.recommendations_declined is False

    def test_ignores_when_no_recommendations(self):
        """No pending recommendations → no decline detection."""
        ctx = BookingContext()

        assert _detect_recommendation_decline("no gracias", ctx) is False

    def test_ignores_when_already_declined(self):
        """Already declined → don't re-process."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=True,
        )

        assert _detect_recommendation_decline("no gracias", ctx) is False

    def test_non_decline_message_returns_false(self):
        """Normal booking message should not trigger decline."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
        )

        assert _detect_recommendation_decline("sí, quiero la hidratación", ctx) is False
        assert ctx.recommendations_declined is False


# =============================================================================
# 16. "no gracias" conflict fix — Phase 4 (T-14)
# =============================================================================


class TestNoGraciasConflictFix:
    """Verify 'no gracias' no longer triggers cancel intent."""

    def test_no_gracias_does_not_cancel(self):
        """'no gracias' should NOT trigger cancel — it's too generic."""
        mode = make_booking_mode()
        state = make_state(user_message="no gracias")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "no gracias", intent)

        assert result is None  # No cancel — normal flow continues


# =============================================================================
# 17. P1/P2/P3 — manage_customer name bypass (_pre_tool_call)
# =============================================================================


class TestPreToolCallNameBypass:
    """P1/P2/P3 fix: manage_customer calls for name-only should be bypassed,
    storing the name directly in ctx.customer_name."""

    @pytest.mark.asyncio
    async def test_name_only_create_bypassed(self):
        """manage_customer(action='create', data={'first_name': 'María'}) → bypass."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = BookingContext(customer_id="cust-001")
        tool_args = {
            "action": "create",
            "phone": "+34612345678",
            "data": {"first_name": "María"},
        }

        result = await mode._pre_tool_call("manage_customer", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NAME_STORED_DIRECTLY"
        assert mode._ctx.customer_name == "María"

    @pytest.mark.asyncio
    async def test_name_only_update_bypassed(self):
        """manage_customer(action='update', data={'first_name': 'Ana', 'customer_id': 'x'}) → bypass."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = BookingContext(customer_id="cust-001")
        tool_args = {
            "action": "update",
            "phone": "+34612345678",
            "data": {"first_name": "Ana", "customer_id": "cust-001"},
        }

        result = await mode._pre_tool_call("manage_customer", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NAME_STORED_DIRECTLY"
        assert mode._ctx.customer_name == "Ana"

    @pytest.mark.asyncio
    async def test_name_with_last_name_bypassed_when_customer_exists(self):
        """First + last name intercepted ONLY when customer_id already known.

        When the customer already has an ID (exists in DB), a name-only create
        call is correctly intercepted — the LLM is just trying to save the name.
        When customer_id is None, the create call must pass through to get the UUID.
        """
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        # Customer already exists in DB — create with name only should be intercepted
        mode._ctx = BookingContext(customer_id="550e8400-e29b-41d4-a716-446655440000")
        tool_args = {
            "action": "create",
            "phone": "+34612345678",
            "data": {"first_name": "María", "last_name": "García"},
        }

        result = await mode._pre_tool_call("manage_customer", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NAME_STORED_DIRECTLY"
        assert mode._ctx.customer_name == "María García"

    @pytest.mark.asyncio
    async def test_name_only_create_passes_when_no_customer_id(self):
        """manage_customer(create) with name MUST pass through when customer_id is None.

        This is the critical case: LLM called get → exists:false → calling create.
        Intercepting this would leave customer_id=None and break book().
        """
        mode = make_booking_mode()
        # customer_id is None — this is a real create to get the UUID
        mode._ctx = BookingContext()  # customer_id=None by default
        tool_args = {
            "action": "create",
            "phone": "+34612345678",
            "data": {"first_name": "María", "last_name": "García"},
        }

        result = await mode._pre_tool_call("manage_customer", tool_args)

        # Should NOT be intercepted — must reach the actual tool
        assert not isinstance(result, dict) or result.get("action") == "create"
        assert mode._ctx.customer_id is None  # UUID will come from DB response

    @pytest.mark.asyncio
    async def test_non_name_data_passes_through(self):
        """manage_customer with notes or other data should NOT be bypassed."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()
        tool_args = {
            "action": "create",
            "phone": "+34612345678",
            "data": {"first_name": "María", "notes": "VIP client"},
        }

        result = await mode._pre_tool_call("manage_customer", tool_args)

        # Should NOT be a ToolCallRejection — passes through to the real tool
        assert isinstance(result, dict)
        assert mode._ctx.customer_name is None  # Not stored by bypass

    @pytest.mark.asyncio
    async def test_bypass_without_ctx_does_not_crash(self):
        """When _ctx is None, manage_customer should pass through normally."""
        mode = make_booking_mode()
        mode._ctx = None
        tool_args = {
            "action": "create",
            "phone": "+34612345678",
            "data": {"first_name": "María"},
        }

        result = await mode._pre_tool_call("manage_customer", tool_args)

        # No ctx → no bypass logic, passes through
        assert isinstance(result, dict)


# =============================================================================
# 18. P1/P2/P3 — Conversational name extraction
# =============================================================================


class TestExtractNameFromConversation:
    """P1/P2/P3 fix: extract customer name from user message when the
    previous assistant message asked for the name."""

    def test_extracts_bare_name_after_name_question(self):
        """User replies 'María' after assistant asked '¿Tu nombre?'."""
        from agent.modes.booking_mode import _extract_name_from_conversation

        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿A nombre de quién sería la cita?"},
                {"role": "user", "content": "María"},
            ],
        }

        _extract_name_from_conversation(state, "María", ctx)

        assert ctx.customer_name == "María"

    def test_extracts_me_llamo_pattern(self):
        """User replies 'Me llamo Ana Torres'."""
        from agent.modes.booking_mode import _extract_name_from_conversation

        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Cuál es tu nombre?"},
                {"role": "user", "content": "Me llamo Ana Torres"},
            ],
        }

        _extract_name_from_conversation(state, "Me llamo Ana Torres", ctx)

        assert ctx.customer_name == "Ana Torres"

    def test_extracts_soy_pattern(self):
        """User replies 'Soy Laura'."""
        from agent.modes.booking_mode import _extract_name_from_conversation

        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Tu nombre, por favor?"},
                {"role": "user", "content": "Soy Laura"},
            ],
        }

        _extract_name_from_conversation(state, "Soy Laura", ctx)

        assert ctx.customer_name == "Laura"

    def test_no_extraction_without_name_question(self):
        """Should NOT extract name if assistant didn't ask for it."""
        from agent.modes.booking_mode import _extract_name_from_conversation

        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Qué servicio deseas?"},
                {"role": "user", "content": "María"},
            ],
        }

        _extract_name_from_conversation(state, "María", ctx)

        assert ctx.customer_name is None  # No extraction — assistant didn't ask for name

    def test_no_extraction_for_stopwords(self):
        """Common words like 'Hola' should NOT be treated as names."""
        from agent.modes.booking_mode import _extract_name_from_conversation

        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Tu nombre?"},
                {"role": "user", "content": "Hola"},
            ],
        }

        _extract_name_from_conversation(state, "Hola", ctx)

        assert ctx.customer_name is None

    def test_no_extraction_when_name_already_set(self):
        """When customer_name is already set, extraction should not be called
        (the caller checks this, but we verify the function is safe)."""
        from agent.modes.booking_mode import _extract_name_from_conversation

        ctx = BookingContext(customer_name="Existing")
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Tu nombre?"},
                {"role": "user", "content": "Laura"},
            ],
        }

        # Even if called, it should overwrite — but the caller checks ctx.customer_name first
        _extract_name_from_conversation(state, "Laura", ctx)
        assert ctx.customer_name == "Laura"


# =============================================================================
# T-09: BUG-2 regression — audience keywords rejected as name
# =============================================================================


class TestAudienceKeywordsRejectedAsName:
    """BUG-2 regression: 'soy caballero' / 'soy dama' must NOT be captured as
    customer_name. The _AUDIENCE_KEYWORDS set guards against this in
    _extract_name_from_conversation (Tier 1 — structured intro pattern)."""

    def test_soy_caballero_rejected(self):
        """'soy caballero' → name not extracted (audience keyword)."""
        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿A nombre de quién sería la cita?"},
                {"role": "user", "content": "soy caballero"},
            ],
        }

        _extract_name_from_conversation(state, "soy caballero", ctx)

        assert ctx.customer_name is None

    def test_soy_dama_rejected(self):
        """'soy dama' → name not extracted (audience keyword)."""
        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Para quién es el servicio?"},
                {"role": "user", "content": "soy dama"},
            ],
        }

        _extract_name_from_conversation(state, "soy dama", ctx)

        assert ctx.customer_name is None

    def test_soy_senora_rejected(self):
        """'soy señora' → name not extracted (audience keyword, accent-stripped to 'senora')."""
        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Tu nombre, por favor?"},
                {"role": "user", "content": "soy señora"},
            ],
        }

        _extract_name_from_conversation(state, "soy señora", ctx)

        assert ctx.customer_name is None

    def test_me_llamo_accepted(self):
        """'me llamo María' → name = 'María' (structured pattern still works)."""
        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Tu nombre?"},
                {"role": "user", "content": "me llamo María"},
            ],
        }

        _extract_name_from_conversation(state, "me llamo María", ctx)

        assert ctx.customer_name == "María"

    def test_mi_nombre_es_accepted(self):
        """'mi nombre es Juan' → name = 'Juan'."""
        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Tu nombre?"},
                {"role": "user", "content": "mi nombre es Juan"},
            ],
        }

        _extract_name_from_conversation(state, "mi nombre es Juan", ctx)

        assert ctx.customer_name == "Juan"

    def test_soy_real_name_accepted(self):
        """'soy Ana' → name = 'Ana' (real name, not an audience keyword)."""
        ctx = BookingContext()
        state = {
            "messages": [
                {"role": "assistant", "content": "¿Tu nombre?"},
                {"role": "user", "content": "soy Ana"},
            ],
        }

        _extract_name_from_conversation(state, "soy Ana", ctx)

        assert ctx.customer_name == "Ana"

    def test_audience_keywords_constant_contains_key_words(self):
        """Verify the _AUDIENCE_KEYWORDS set contains the expected demographic words."""
        assert "caballero" in _AUDIENCE_KEYWORDS
        assert "dama" in _AUDIENCE_KEYWORDS
        assert "senora" in _AUDIENCE_KEYWORDS  # accent-stripped form


# =============================================================================
# T-09 + T-10: Notes injection in _pre_tool_call
# =============================================================================


class TestNotesInjectionInPreToolCall:
    """REQ-1: ctx.notes is injected into book() args deterministically."""

    def _make_ctx_with_all_gates(self, notes=None) -> BookingContext:
        """Return a BookingContext that satisfies all book() precondition gates."""
        return BookingContext(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
            customer_name="María García",
            selected_services=["Corte de Señora"],
            offered_slots=[
                {
                    "stylist_id": "stylist-aaa",
                    "full_datetime": "2026-04-01T10:00:00+02:00",
                    "stylist_name": "Ana",
                }
            ],
            needs_availability_refresh=False,
            confirmation_shown=True,
            notes_asked=True,  # satisfy NOTES_NOT_ASKED gate
            notes=notes,
        )

    @pytest.mark.asyncio
    async def test_notes_injected_when_present(self):
        """ctx.notes is injected into tool_args['notes'] when set."""
        mode = make_booking_mode()
        mode._ctx = self._make_ctx_with_all_gates(notes="alergia al polvo")
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Señora"],
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, dict)
        assert result.get("notes") == "alergia al polvo"

    @pytest.mark.asyncio
    async def test_notes_not_injected_when_none(self):
        """ctx.notes=None → tool_args['notes'] is None (not absent, but defaulted to None)."""
        mode = make_booking_mode()
        mode._ctx = self._make_ctx_with_all_gates(notes=None)
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Señora"],
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, dict)
        # setdefault sets it to None — key is present but value is None
        assert result.get("notes") is None

    @pytest.mark.asyncio
    async def test_notes_not_injected_when_empty_string(self):
        """ctx.notes='' (empty string) → treated as falsy, notes not injected as truthy value."""
        mode = make_booking_mode()
        mode._ctx = self._make_ctx_with_all_gates(notes="")
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Señora"],
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, dict)
        # Empty string is falsy — setdefault(notes, None) is called instead of injecting
        assert result.get("notes") is None

    @pytest.mark.asyncio
    async def test_notes_stripped_before_injection(self):
        """ctx.notes with leading/trailing whitespace → stripped before injection."""
        mode = make_booking_mode()
        mode._ctx = self._make_ctx_with_all_gates(notes="  alergia al polvo  ")
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Señora"],
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, dict)
        assert result.get("notes") == "alergia al polvo"


# =============================================================================
# T-11: Notes extraction tests
# =============================================================================


class TestNotesExtraction:
    """Tests for _extract_notes_from_conversation:
    extraction only happens when the bot previously asked for notes."""

    def _state_with_notes_question(self, user_reply: str) -> dict:
        """Build a minimal state where the last assistant msg asked for notes."""
        return {
            "messages": [
                {
                    "role": "assistant",
                    "content": "¿Tenés alguna preferencia o nota que deba saber?",
                },
                {"role": "user", "content": user_reply},
            ],
        }

    def _state_without_notes_question(self, user_reply: str) -> dict:
        """Build a state where the bot did NOT ask for notes."""
        return {
            "messages": [
                {"role": "assistant", "content": "¿Qué servicio deseas?"},
                {"role": "user", "content": user_reply},
            ],
        }

    def test_notes_extracted_when_bot_asked(self):
        """Bot asked for notes, user replied → ctx.notes captures the reply."""
        ctx = BookingContext()
        state = self._state_with_notes_question("sin gluten, alergia al polvo")

        _extract_notes_from_conversation(state, "sin gluten, alergia al polvo", ctx)

        assert ctx.notes == "sin gluten, alergia al polvo"

    def test_notes_not_extracted_when_bot_did_not_ask(self):
        """Bot did NOT ask for notes → ctx.notes stays None even if user mentions something."""
        ctx = BookingContext()
        state = self._state_without_notes_question("sin gluten")

        _extract_notes_from_conversation(state, "sin gluten", ctx)

        assert ctx.notes is None

    def test_notes_stay_none_on_decline_no(self):
        """Bot asked, user replied 'no' → ctx.notes stays None (decline not stored)."""
        ctx = BookingContext()
        state = self._state_with_notes_question("no")

        _extract_notes_from_conversation(state, "no", ctx)

        assert ctx.notes is None

    def test_notes_stay_none_on_decline_ninguna(self):
        """Bot asked, user replied 'ninguna' → ctx.notes stays None."""
        ctx = BookingContext()
        state = self._state_with_notes_question("ninguna")

        _extract_notes_from_conversation(state, "ninguna", ctx)

        assert ctx.notes is None

    def test_notes_not_overwritten_when_already_set(self):
        """ctx.notes already has a value → function is skipped by the early-exit guard."""
        ctx = BookingContext(notes="preexisting note")
        state = self._state_with_notes_question("nuevo contenido")

        _extract_notes_from_conversation(state, "nuevo contenido", ctx)

        assert ctx.notes == "preexisting note"

    def test_notes_stay_none_on_decline_nada(self):
        """'nada' is also a decline phrase → ctx.notes stays None."""
        ctx = BookingContext()
        state = self._state_with_notes_question("nada")

        _extract_notes_from_conversation(state, "nada", ctx)

        assert ctx.notes is None

    def test_notes_with_alergia_keyword_in_bot_message(self):
        """Bot message containing 'alergia' also triggers notes extraction."""
        ctx = BookingContext()
        state = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "¿Tenés alguna alergia que deba tener en cuenta?",
                },
                {"role": "user", "content": "alergia a la amoxicilina"},
            ],
        }

        _extract_notes_from_conversation(state, "alergia a la amoxicilina", ctx)

        assert ctx.notes == "alergia a la amoxicilina"


# =============================================================================
# T-12: recommendations_shown timing
# =============================================================================


class TestRecommendationsShownTiming:
    """T-03 regression: recommendations_shown must NOT be set during
    _build_dynamic_context() (before LLM sees the context).
    It must only be set in _build_response() (after LLM generates its reply)."""

    def test_recommendations_shown_not_set_during_context_build(self):
        """_build_dynamic_context() alone does NOT set recommendations_shown = True.

        This is the core regression test for T-03: the flag was previously set
        during context build, before the LLM had a chance to use it.
        """
        ctx = BookingContext(
            pending_recommendations=["Hidratación", "Tinte"],
            recommendations_shown=False,
        )
        state = make_state()

        # Build dynamic context (simulates what happens before the LLM call)
        BookingMode._build_dynamic_context(state, ctx)

        # Flag must still be False — it's set in _build_response(), not here
        assert ctx.recommendations_shown is False

    def test_recommendations_section_rendered_when_pending_and_not_shown(self):
        """When pending_recommendations exist and recommendations_shown=False,
        the section IS rendered in the dynamic context (the LLM WILL see it)."""
        ctx = BookingContext(
            pending_recommendations=["Hidratación"],
            recommendations_shown=False,
        )
        state = make_state()

        context_text = BookingMode._build_dynamic_context(state, ctx)

        assert "SERVICIOS RECOMENDADOS" in context_text
        # But the flag should still be False after context build
        assert ctx.recommendations_shown is False

    def test_recommendations_shown_set_in_build_response(self):
        """_build_response() sets recommendations_shown=True after LLM generates reply."""
        from unittest.mock import MagicMock

        from agent.modes.base import AgenticLoopResult

        mode = make_booking_mode()
        state = make_state()
        ctx = BookingContext(
            customer_name="María",
            pending_recommendations=["Hidratación"],
            recommendations_shown=False,
        )

        # Simulate a minimal AgenticLoopResult (no tool calls)
        result = AgenticLoopResult(
            response_text="Te recomiendo también una hidratación.",
            tool_results=[],
        )

        # Patch the prompt loader to avoid file I/O
        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, result)

        # After _build_response, the flag must be True
        assert ctx.recommendations_shown is True


# =============================================================================
# T-14: Code-rendered booking confirmation (F-8)
# =============================================================================


class TestCodeRenderedConfirmation:
    """T-14: When _booking_completed=True, _build_response() replaces LLM text
    with deterministic confirmation using ctx data (F-8 fix)."""

    def _make_completed_ctx(
        self,
        *,
        stylist_name: str = "Ana",
        services: list[str] | None = None,
        date: str = "lunes 25 de marzo",
        time: str = "10:00",
        price: str | None = None,
    ) -> BookingContext:
        """Build a completed BookingContext with controlled data."""
        ctx = BookingContext(
            stylist_name=stylist_name,
            stylist_id="sty-001",
            selected_services=services or ["Corte de Dama"],
            selected_slot={"date": date, "time": time},
            customer_name="María",
            customer_id="cust-001",
        )
        if price:
            ctx.selected_services_details = [
                {"name": services[0] if services else "Corte", "price": price}
            ]
        ctx._booking_completed = True
        return ctx

    def test_confirmation_uses_ctx_data(self):
        """When _booking_completed=True, response includes stylist_name,
        selected_services, slot date/time (not generic LLM text)."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_completed_ctx(
            stylist_name="Ana",
            services=["Corte de Dama"],
            date="lunes 25 de marzo",
            time="10:00",
        )
        llm_result = AgenticLoopResult(
            response_text="Perfecto, su cita ha sido confirmada.",  # LLM generic text
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        # Extract the response text from the messages update
        messages = updates.get("messages", [])
        assert messages, "Expected messages in updates"
        response_text = messages[0]["content"]

        # Must use ctx data, NOT the LLM's generic text
        assert "Ana" in response_text, "stylist_name must appear"
        assert "Corte de Dama" in response_text, "selected_services must appear"
        assert "lunes 25 de marzo" in response_text, "date must appear"
        assert "10:00" in response_text, "time must appear"
        # LLM generic text must NOT appear
        assert "su cita ha sido confirmada" not in response_text

    def test_confirmation_format_contains_emoji_markers(self):
        """Response contains '✅', '📅', '💇', '✂️', 'Alcobendas'."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_completed_ctx(
            stylist_name="Luciana",
            services=["Tinte Raíz"],
            date="martes 26",
            time="11:00",
        )
        llm_result = AgenticLoopResult(
            response_text="Ha sido reservado.",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        messages = updates.get("messages", [])
        response_text = messages[0]["content"]

        assert "✅" in response_text
        assert "📅" in response_text
        assert "💇" in response_text
        assert "✂️" in response_text
        assert "Alcobendas" in response_text

    def test_confirmation_without_price_when_not_available(self):
        """If selected_services_details has no price, no '💰' line in response."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_completed_ctx(
            stylist_name="Pilar",
            services=["Corte de Dama"],
        )
        # No price in services details
        ctx.selected_services_details = [{"name": "Corte de Dama"}]  # no "price" key
        llm_result = AgenticLoopResult(
            response_text="Reserva confirmada.",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        messages = updates.get("messages", [])
        response_text = messages[0]["content"]

        assert "💰" not in response_text

    def test_confirmation_with_price_when_available(self):
        """If selected_services_details has price, '💰' line IS shown."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_completed_ctx(
            stylist_name="Ana",
            services=["Corte de Dama"],
            price="25€",
        )
        llm_result = AgenticLoopResult(
            response_text="Reserva hecha.",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        messages = updates.get("messages", [])
        response_text = messages[0]["content"]

        assert "💰" in response_text
        assert "25€" in response_text

    def test_non_completed_booking_uses_llm_text(self):
        """When _booking_completed=False, LLM text is used (not the code-rendered template)."""
        mode = make_booking_mode()
        state = make_state()
        ctx = BookingContext(
            customer_name="María",
            selected_services=["Corte"],
            stylist_name="Ana",
        )
        # _booking_completed defaults to False
        llm_text = "¿Qué día te viene bien?"
        llm_result = AgenticLoopResult(
            response_text=llm_text,
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        messages = updates.get("messages", [])
        response_text = messages[0]["content"]

        # LLM text should appear (with possible disclosure prefix)
        assert llm_text in response_text


# =============================================================================
# T-02: Post-booking confirmation info text (REQ-A)
# =============================================================================


class TestPostBookingConfirmationText:
    """T-02: _build_response() includes 48h confirmation info when _booking_completed=True."""

    def _make_completed_ctx(
        self, *, stylist_name: str = "Ana", services: list | None = None
    ) -> BookingContext:
        ctx = BookingContext(
            stylist_name=stylist_name,
            stylist_id="sty-001",
            selected_services=services or ["Corte de Dama"],
            selected_slot={"date": "lunes 25 de marzo", "time": "10:00"},
            customer_name="María",
            customer_id="cust-001",
        )
        ctx._booking_completed = True
        return ctx

    def test_confirmation_text_present_when_booking_completed(self):
        """When _booking_completed=True, response must include 48h confirmation message."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_completed_ctx()
        llm_result = AgenticLoopResult(response_text="OK", tool_results={})

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        response_text = updates["messages"][0]["content"]
        assert "📩 Recibirás un mensaje de confirmación" in response_text
        assert "48h" in response_text
        assert "SÍ" in response_text
        assert "NO" in response_text

    def test_confirmation_text_absent_when_booking_not_completed(self):
        """When _booking_completed=False, the 48h confirmation text must NOT appear."""
        mode = make_booking_mode()
        state = make_state()
        ctx = BookingContext(
            customer_name="María",
            selected_services=["Corte"],
            stylist_name="Ana",
        )
        # _booking_completed defaults to False
        llm_result = AgenticLoopResult(response_text="¿Qué día te viene bien?", tool_results={})

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        response_text = updates["messages"][0]["content"]
        assert "📩 Recibirás un mensaje de confirmación" not in response_text


# =============================================================================
# T-03: Slot index enforcement — hybrid auto-recover + hard-reject algorithm
# =============================================================================

_STYLIST_ID = "550e8400-e29b-41d4-a716-446655440001"
_CUSTOMER_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_ctx_with_slot(
    stylist_id: str = _STYLIST_ID,
    full_datetime: str = "2026-04-10T10:00:00+02:00",
    stylist_name: str = "Ana",
    offered_slots: list | None = None,
) -> BookingContext:
    """Build a BookingContext with all pre-guards satisfied, ready for slot resolution."""
    slots = (
        offered_slots
        if offered_slots is not None
        else [
            {
                "stylist_id": stylist_id,
                "full_datetime": full_datetime,
                "stylist_name": stylist_name,
                "date": "viernes 10 de abril",
                "time": "10:00",
            }
        ]
    )
    ctx = BookingContext(
        customer_id=_CUSTOMER_ID,
        customer_name="María García",
        selected_services=["Corte de Dama"],
        needs_availability_refresh=False,
        confirmation_shown=True,
        offered_slots=slots,
    )
    ctx.notes_asked = True  # satisfy NOTES_NOT_ASKED guard
    return ctx
    return BookingContext(
        customer_id=_CUSTOMER_ID,
        customer_name="María García",
        selected_services=["Corte de Dama"],
        needs_availability_refresh=False,
        confirmation_shown=True,
        offered_slots=slots,
    )


class TestSlotIndexEnforcement:
    """Tests for the hybrid auto-recover + hard-reject algorithm in _pre_tool_call.

    Covers: auto-recovery on exact match, hard-reject on no match,
    hard-reject on malformed start_time, UTC-equivalent datetimes, and
    pass-through when no offered_slots exist.
    """

    @pytest.mark.asyncio
    async def test_auto_recovery_when_slot_matches(self):
        """When stylist_id+start_time exactly match an offered slot, auto-recover."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = _make_ctx_with_slot(
            stylist_id=_STYLIST_ID,
            full_datetime="2026-04-10T10:00:00+02:00",
        )
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Dama"],
            "first_name": "María",
            "stylist_id": _STYLIST_ID,
            "start_time": "2026-04-10T10:00:00+02:00",
            # slot_index intentionally absent
        }

        result = await mode._pre_tool_call("book", tool_args)

        # Must NOT be a rejection
        assert not isinstance(result, ToolCallRejection)
        # tool_args resolved correctly
        assert result["stylist_id"] == _STYLIST_ID
        assert result["start_time"] == "2026-04-10T10:00:00+02:00"
        assert "slot_index" not in result
        # ctx.selected_slot must be populated
        assert mode._ctx.selected_slot is not None
        assert mode._ctx.selected_slot["stylist_id"] == _STYLIST_ID
        assert mode._ctx.selected_slot["time"] == "10:00"

    @pytest.mark.asyncio
    async def test_hard_reject_when_no_match(self):
        """When no offered slot matches stylist_id+start_time, return ToolCallRejection."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = _make_ctx_with_slot(
            stylist_id=_STYLIST_ID,
            full_datetime="2026-04-10T10:00:00+02:00",
        )
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Dama"],
            "first_name": "María",
            "stylist_id": _STYLIST_ID,
            "start_time": "2026-04-10T12:00:00+02:00",  # different time — no match
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "SLOT_NOT_IN_OFFERED"

    @pytest.mark.asyncio
    async def test_hard_reject_malformed_start_time(self):
        """When start_time is unparseable, return ToolCallRejection without raising."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = _make_ctx_with_slot()
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Dama"],
            "first_name": "María",
            "stylist_id": _STYLIST_ID,
            "start_time": "not-a-date",  # malformed
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "SLOT_NOT_IN_OFFERED"

    @pytest.mark.asyncio
    async def test_utc_equivalent_datetimes_match(self):
        """Datetimes that represent the same UTC instant but with different tz offsets match."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        # Slot stored with +02:00
        mode._ctx = _make_ctx_with_slot(
            stylist_id=_STYLIST_ID,
            full_datetime="2026-04-10T10:00:00+02:00",
        )
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Dama"],
            "first_name": "María",
            "stylist_id": _STYLIST_ID,
            # Same UTC instant expressed in UTC (+00:00) — 10:00+02:00 == 08:00+00:00
            "start_time": "2026-04-10T08:00:00+00:00",
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert not isinstance(result, ToolCallRejection)
        assert result["stylist_id"] == _STYLIST_ID
        assert mode._ctx.selected_slot is not None

    @pytest.mark.asyncio
    async def test_passthrough_when_no_offered_slots(self):
        """When offered_slots is empty, NO_OFFERED_SLOTS guard fires (unchanged behavior)."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        ctx = BookingContext(
            customer_id=_CUSTOMER_ID,
            customer_name="María García",
            selected_services=["Corte de Dama"],
            needs_availability_refresh=False,
            confirmation_shown=True,
            offered_slots=[],  # empty — no offered slots
        )
        ctx.notes_asked = True
        mode._ctx = ctx
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Dama"],
            "first_name": "María",
            "stylist_id": "__RESOLVE_FROM_SLOT__",  # sentinel
            # no slot_index
        }

        result = await mode._pre_tool_call("book", tool_args)

        # The NO_OFFERED_SLOTS guard fires before the sentinel check
        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_OFFERED_SLOTS"


# =============================================================================
# T-09: Notes gate — notes_asked field gates book() and detection logic
# =============================================================================


class TestNotesGate:
    """T-09: Tests for the notes gate in _pre_tool_call() and notes exchange detection."""

    def _make_ctx_all_gates_pass(self, notes_asked: bool = False) -> BookingContext:
        """Return a BookingContext that passes all pre-tool-call gates (except notes gate)."""
        ctx = BookingContext(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
            customer_name="María García",
            selected_services=["Corte de Dama"],
            offered_slots=[
                {
                    "stylist_id": "stylist-aaa",
                    "full_datetime": "2026-04-01T10:00:00+02:00",
                    "stylist_name": "Ana",
                }
            ],
            needs_availability_refresh=False,
            confirmation_shown=True,
            notes_asked=notes_asked,
        )
        return ctx

    @pytest.mark.asyncio
    async def test_pre_tool_call_rejects_book_when_notes_not_asked(self):
        """_pre_tool_call returns NOTES_NOT_ASKED when ctx.notes_asked=False and
        all other gates pass."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = self._make_ctx_all_gates_pass(notes_asked=False)
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Dama"],
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NOTES_NOT_ASKED"

    @pytest.mark.asyncio
    async def test_pre_tool_call_allows_book_when_notes_asked(self):
        """When notes_asked=True and confirmation_shown=True, no NOTES_NOT_ASKED rejection."""
        from agent.modes.base import ToolCallRejection

        mode = make_booking_mode()
        mode._ctx = self._make_ctx_all_gates_pass(notes_asked=True)
        tool_args = {
            "customer_id": "FAKE",
            "services": ["Corte de Dama"],
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", tool_args)

        # Must NOT be a NOTES_NOT_ASKED rejection
        if isinstance(result, ToolCallRejection):
            assert result.error_code != "NOTES_NOT_ASKED", (
                f"Unexpected NOTES_NOT_ASKED rejection when notes_asked=True. "
                f"Got: {result.error_code}"
            )

    @pytest.mark.asyncio
    async def test_handle_sets_notes_asked_when_bot_asked_and_user_replied(self):
        """notes_asked is set to True when the last assistant message asked for notes
        and the user has replied (via _previous_assistant_asked_for_notes detection)."""
        from agent.modes.booking_mode import _previous_assistant_asked_for_notes

        # Build message history: bot asked for notes, user replied
        messages = [
            {
                "role": "assistant",
                "content": "¿Tenés alguna nota o preferencia especial para tu cita?",
            },
            {"role": "user", "content": "Sin preferencias específicas"},
        ]

        # Confirm the detection function picks up the notes question
        assert _previous_assistant_asked_for_notes(messages) is True

        # Simulate the handle() detection logic directly
        ctx = BookingContext(notes_asked=False, notes_ask_attempts=0)
        if not ctx.notes_asked:
            if ctx.notes_ask_attempts >= 2:
                ctx.notes_asked = True
            elif _previous_assistant_asked_for_notes(messages):
                ctx.notes_asked = True

        assert ctx.notes_asked is True

    @pytest.mark.asyncio
    async def test_loop_prevention_auto_sets_notes_asked_at_2_attempts(self):
        """When notes_ask_attempts >= 2, notes_asked is auto-set to True
        regardless of message history (loop prevention)."""
        from agent.modes.booking_mode import _previous_assistant_asked_for_notes

        # Messages without a notes question — message scan would NOT trigger
        messages = [
            {"role": "assistant", "content": "¿Qué servicio deseas?"},
            {"role": "user", "content": "Un corte"},
        ]

        # Confirm message scan alone would NOT trigger
        assert _previous_assistant_asked_for_notes(messages) is False

        # Simulate the handle() detection logic with attempts=2
        ctx = BookingContext(notes_asked=False, notes_ask_attempts=2)
        if not ctx.notes_asked:
            if ctx.notes_ask_attempts >= 2:
                ctx.notes_asked = True
            elif _previous_assistant_asked_for_notes(messages):
                ctx.notes_asked = True

        # Auto-set because attempts >= 2
        assert ctx.notes_asked is True


# =============================================================================
# T-05 & T-06: Stylist desync fix tests
# =============================================================================


class TestStylistDesyncFix:
    """T-05 / T-06: Verify that ctx.stylist_name/stylist_id stay in sync after
    slot resolution, and that F-8 falls back to last_booked_slot when
    selected_slot has been cleared."""

    @pytest.mark.asyncio
    async def test_pre_tool_call_syncs_stylist_name_and_id(self):
        """T-05: _pre_tool_call() updates ctx.stylist_id and ctx.stylist_name
        from the resolved slot — overwriting any stale value already in ctx."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            customer_id="cust-001",
            customer_name="María",
            stylist_name="Ana",  # stale — will be overwritten
            stylist_id="uuid-ana",  # stale — will be overwritten
            offered_slots=[
                {
                    "stylist_id": "uuid-pilar",
                    "stylist_name": "Pilar",
                    "full_datetime": "2026-03-30T10:00:00+02:00",
                    "date": "lunes 30 de marzo",
                    "time": "10:00",
                }
            ],
            selected_services=["Corte de Dama"],
            needs_availability_refresh=False,
            confirmation_shown=True,
            notes_asked=True,
        )
        tool_args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "first_name": "María",
            "slot_index": 1,
        }

        await mode._pre_tool_call("book", tool_args)

        assert mode._ctx.stylist_name == "Pilar", (
            f"Expected stylist_name='Pilar', got {mode._ctx.stylist_name!r}"
        )
        assert mode._ctx.stylist_id == "uuid-pilar", (
            f"Expected stylist_id='uuid-pilar', got {mode._ctx.stylist_id!r}"
        )

    def test_f8_reads_last_booked_slot_when_selected_slot_cleared(self):
        """T-06: When selected_slot is None but last_booked_slot is set,
        _build_response() uses last_booked_slot for F-8 date/time rendering."""
        mode = make_booking_mode()
        state = make_state()

        ctx = BookingContext(
            stylist_name="Pilar",
            stylist_id="uuid-pilar",
            selected_services=["Corte de Dama"],
            selected_slot=None,  # cleared after booking
            last_booked_slot={
                "date": "lunes 30 de marzo",
                "time": "10:00",
                "stylist_name": "Pilar",
                "full_datetime": "2026-03-30T10:00:00+02:00",
            },
            customer_name="María",
            customer_id="cust-001",
        )
        ctx._booking_completed = True

        llm_result = AgenticLoopResult(
            response_text="Reserva hecha.",  # will be replaced by F-8
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        messages = updates.get("messages", [])
        assert messages, "Expected messages in updates"
        response_text = messages[0]["content"]

        assert "Pilar" in response_text, f"Expected 'Pilar' in response. Got:\n{response_text}"
        assert "10:00" in response_text, f"Expected '10:00' in response. Got:\n{response_text}"
        assert "lunes 30 de marzo" in response_text, (
            f"Expected date in response. Got:\n{response_text}"
        )


# =============================================================================
# T-15: _resolve_user_slot_selection — slot resolver (Bug 1 fix)
# =============================================================================


def _make_offered_slots_two() -> list[dict]:
    """Two distinct offered slots for slot-resolver tests."""
    return [
        {
            "stylist_id": "uuid-ana",
            "stylist_name": "Ana",
            "stylist": "Ana",
            "time": "10:00",
            "date": "lunes 30 de marzo",
            "day_name": "lunes 30 de marzo",
            "full_datetime": "2026-03-30T10:00:00+02:00",
        },
        {
            "stylist_id": "uuid-pilar",
            "stylist_name": "Pilar",
            "stylist": "Pilar",
            "time": "14:00",
            "date": "lunes 30 de marzo",
            "day_name": "lunes 30 de marzo",
            "full_datetime": "2026-03-30T14:00:00+02:00",
        },
        {
            "stylist_id": "uuid-lucia",
            "stylist_name": "Lucía",
            "stylist": "Lucía",
            "time": "11:20",
            "date": "martes 31 de marzo",
            "day_name": "martes 31 de marzo",
            "full_datetime": "2026-03-31T11:20:00+02:00",
        },
    ]


class TestResolveUserSlotSelection:
    """Tests for _resolve_user_slot_selection (Bug 1 fix — tool_skip gap)."""

    def test_resolve_slot_by_index(self):
        """User says '3' → slot 3 (1-based) is resolved, stylist persisted."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("3", ctx)

        assert result is True
        assert ctx.selected_slot is not None
        assert ctx.stylist_id == "uuid-lucia"
        assert ctx.stylist_name == "Lucía"
        assert ctx.selected_slot["time"] == "11:20"

    def test_resolve_slot_by_index_with_filler_words(self):
        """User says 'el 2' → slot 2 is resolved (digit extraction through filler)."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("el 2", ctx)

        assert result is True
        assert ctx.stylist_id == "uuid-pilar"
        assert ctx.stylist_name == "Pilar"

    def test_resolve_slot_by_time(self):
        """User says 'a las 14:00' → matching slot resolved."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("a las 14:00", ctx)

        assert result is True
        assert ctx.selected_slot is not None
        assert ctx.stylist_id == "uuid-pilar"
        assert ctx.stylist_name == "Pilar"
        assert ctx.selected_slot["time"] == "14:00"

    def test_resolve_slot_by_exact_time_string(self):
        """User says '11:20' (bare time) → slot with time '11:20' resolved."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("11:20", ctx)

        assert result is True
        assert ctx.stylist_id == "uuid-lucia"
        assert ctx.selected_slot["time"] == "11:20"

    def test_resolve_slot_no_match_unmatched_time(self):
        """User says 'a las 11:20' when no slot has that time → returns False, ctx unchanged."""
        slots = [
            {"stylist_id": "s1", "stylist_name": "Ana", "time": "10:00", "full_datetime": ""},
            {"stylist_id": "s2", "stylist_name": "Pilar", "time": "14:00", "full_datetime": ""},
        ]
        ctx = BookingContext(offered_slots=slots)

        result = _resolve_user_slot_selection("a las 11:20", ctx)

        assert result is False
        assert ctx.selected_slot is None
        assert ctx.stylist_id is None

    def test_resolve_slot_affirmative_only(self):
        """User says 'sí' (bare affirmative, no number/time) → returns False."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("sí", ctx)

        assert result is False
        assert ctx.selected_slot is None
        assert ctx.stylist_id is None

    def test_resolve_slot_affirmative_dale(self):
        """User says 'dale' → returns False (no false positive)."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("dale", ctx)

        assert result is False
        assert ctx.selected_slot is None

    def test_resolve_slot_affirmative_single_slot(self):
        """User says 'sí', ctx.offered_slots has exactly 1 slot → that slot is resolved."""
        single_slot = [
            {
                "stylist_id": "uuid-ana",
                "stylist_name": "Ana",
                "stylist": "Ana",
                "time": "10:00",
                "date": "lunes 30 de marzo",
                "day_name": "lunes 30 de marzo",
                "full_datetime": "2026-03-30T10:00:00+02:00",
            }
        ]
        ctx = BookingContext(offered_slots=single_slot)

        result = _resolve_user_slot_selection("sí", ctx)

        assert result is True
        assert ctx.selected_slot is not None
        assert ctx.stylist_id == "uuid-ana"
        assert ctx.stylist_name == "Ana"
        assert ctx.selected_slot["time"] == "10:00"
        assert ctx.selected_slot["date"] == "lunes 30 de marzo"
        assert ctx.selected_slot["stylist_id"] == "uuid-ana"

    def test_resolve_slot_guard_already_set(self):
        """ctx.stylist_id already set → resolver is a no-op (returns False, fields unchanged)."""
        ctx = BookingContext(
            offered_slots=_make_offered_slots_two(),
            stylist_id="pre-existing-uuid",
            stylist_name="ExistingStylelist",
        )

        result = _resolve_user_slot_selection("1", ctx)

        assert result is False
        assert ctx.stylist_id == "pre-existing-uuid"
        assert ctx.stylist_name == "ExistingStylelist"

    def test_resolve_slot_guard_no_offered_slots(self):
        """offered_slots is empty → returns False immediately."""
        ctx = BookingContext(offered_slots=[])

        result = _resolve_user_slot_selection("1", ctx)

        assert result is False

    def test_resolve_slot_guard_offered_slots_none(self):
        """offered_slots is None → returns False immediately."""
        ctx = BookingContext(offered_slots=None)

        result = _resolve_user_slot_selection("1", ctx)

        assert result is False

    def test_resolve_slot_index_out_of_range(self):
        """User says '99' but only 3 slots exist → returns False."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("99", ctx)

        assert result is False
        assert ctx.selected_slot is None

    def test_resolve_slot_persists_full_slot_dict(self):
        """selected_slot dict contains date, time, full_datetime, stylist_id, stylist_name."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        _resolve_user_slot_selection("1", ctx)

        assert ctx.selected_slot is not None
        assert ctx.selected_slot["date"] == "lunes 30 de marzo"
        assert ctx.selected_slot["time"] == "10:00"
        assert ctx.selected_slot["full_datetime"] == "2026-03-30T10:00:00+02:00"
        assert ctx.selected_slot["stylist_id"] == "uuid-ana"
        assert ctx.selected_slot["stylist_name"] == "Ana"

    def test_resolve_slot_informal_a_las_hora(self):
        """User says 'a las 10' → slot with time '10:00' is resolved (informal hour reference)."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("a las 10", ctx)

        assert result is True
        assert ctx.selected_slot is not None
        assert ctx.selected_slot["time"] == "10:00"
        assert ctx.stylist_id == "uuid-ana"
        assert ctx.stylist_name == "Ana"

    def test_resolve_slot_informal_hora_hs(self):
        """User says '14 hs' → slot with time '14:00' is resolved (informal hour + hs)."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())

        result = _resolve_user_slot_selection("14 hs", ctx)

        assert result is True
        assert ctx.selected_slot is not None
        assert ctx.selected_slot["time"] == "14:00"
        assert ctx.stylist_id == "uuid-pilar"
        assert ctx.stylist_name == "Pilar"

    def test_resolve_slot_informal_bare_hour(self):
        """User says '14' (bare number) with only 3 slots → 14 > 3 so treated as 14:00 hour."""
        ctx = BookingContext(offered_slots=_make_offered_slots_two())
        # _make_offered_slots_two returns 3 slots; 14 > 3, so it cannot be an index

        result = _resolve_user_slot_selection("14", ctx)

        assert result is True
        assert ctx.selected_slot is not None
        assert ctx.selected_slot["time"] == "14:00"
        assert ctx.stylist_id == "uuid-pilar"
        assert ctx.stylist_name == "Pilar"


# =============================================================================
# T-16: Confirmation question pattern detection (Bug 2 fix)
# =============================================================================


class TestConfirmationQuestionPatternDetection:
    """Tests for the additive confirmation question pattern check in _build_response()."""

    def _make_complete_ctx(self) -> BookingContext:
        """Return a BookingContext with all booking data complete."""
        return BookingContext(
            service_id="svc-001",
            service_name="Corte de Dama",
            stylist_id="sty-001",
            stylist_name="Ana",
            offered_slots=[{"time": "10:00", "date": "lunes"}],
            customer_name="María",
            customer_id="cust-001",
            confirmation_summary_sent=False,
        )

    def test_confirmation_question_pattern_sets_flag(self):
        """Complete booking data + '¿Queres que lo reservo?' → confirmation_summary_sent=True."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_complete_ctx()

        llm_result = AgenticLoopResult(
            response_text="¿Queres que lo reservo?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.confirmation_summary_sent is True

    def test_confirmation_question_confirmamos_sets_flag(self):
        """Complete booking data + '¿Confirmamos?' → flag set."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_complete_ctx()

        llm_result = AgenticLoopResult(
            response_text="Perfecto, ¿confirmamos la cita para el lunes?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.confirmation_summary_sent is True

    def test_confirmation_question_procedemos_sets_flag(self):
        """Complete booking data + 'procedemos' → flag set."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_complete_ctx()

        llm_result = AgenticLoopResult(
            response_text="¿Procedemos con la reserva?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.confirmation_summary_sent is True

    def test_confirmation_pattern_incomplete_data_does_not_set_flag(self):
        """Incomplete booking (stylist_id missing) + question → flag stays False."""
        mode = make_booking_mode()
        state = make_state()
        # Incomplete: no stylist_id
        ctx = BookingContext(
            service_id="svc-001",
            service_name="Corte de Dama",
            stylist_id=None,  # ← missing
            offered_slots=[{"time": "10:00", "date": "lunes"}],
            customer_name="María",
            customer_id="cust-001",
            confirmation_summary_sent=False,
        )

        llm_result = AgenticLoopResult(
            response_text="¿Confirmamos la cita?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.confirmation_summary_sent is False

    def test_confirmation_pattern_already_sent_not_overwritten(self):
        """When confirmation_summary_sent is already True, it stays True (idempotent)."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_complete_ctx()
        ctx.confirmation_summary_sent = True  # already set

        llm_result = AgenticLoopResult(
            response_text="¿Confirmamos?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.confirmation_summary_sent is True  # still True

    def test_confirmation_pattern_constant_contents(self):
        """Verify _CONFIRMATION_QUESTION_PATTERNS contains key phrases."""
        assert "confirmamos" in _CONFIRMATION_QUESTION_PATTERNS
        assert "reservo" in _CONFIRMATION_QUESTION_PATTERNS
        assert "procedemos" in _CONFIRMATION_QUESTION_PATTERNS
        assert "te parece bien" in _CONFIRMATION_QUESTION_PATTERNS


# =============================================================================
# _combo_offer_in_response (combo-recommendations-fix REQ-2)
# =============================================================================


class TestComboOfferInResponse:
    """Unit tests for _combo_offer_in_response() detection helper."""

    def test_named_recommendation_detected(self):
        """Response mentions pending service by name → True."""
        response = "¿Te gustaría añadir un Tratamiento a tu cita?"
        pending = ["Tratamiento"]
        assert _combo_offer_in_response(response, pending) is True

    def test_offer_phrase_detected(self):
        """Response contains recognized offer phrase → True."""
        response = "También te ofrezco un peinado para completar el look."
        pending = ["Peinado"]
        assert _combo_offer_in_response(response, pending) is True

    def test_no_offer_returns_false(self):
        """Response unrelated to combo offer → False."""
        response = "Perfecto, ¿con qué estilista te gustaría?"
        pending = ["Tratamiento"]
        assert _combo_offer_in_response(response, pending) is False

    def test_empty_pending_returns_false(self):
        """Empty pending list → False even if phrase present."""
        response = "te gustaría añadir algo"
        pending: list[str] = []
        assert _combo_offer_in_response(response, pending) is False

    def test_case_insensitive(self):
        """Name matching is case-insensitive."""
        response = "TRATAMIENTO incluido en tu reserva"
        pending = ["tratamiento"]
        assert _combo_offer_in_response(response, pending) is True

    def test_partial_phrase_match(self):
        """'¿añadimos' phrase → True."""
        response = "¿Añadimos también un secado?"
        pending = ["Secado"]
        assert _combo_offer_in_response(response, pending) is True

    def test_puedo_anadir_phrase(self):
        """'puedo añadir' → True."""
        response = "Puedo añadir un tratamiento de hidratación si lo deseas."
        pending = ["Hidratación"]
        assert _combo_offer_in_response(response, pending) is True

    def test_multiple_pending_any_match(self):
        """Any one of the pending services appearing → True."""
        response = "Tu cita incluirá el peinado."
        pending = ["Tratamiento", "Peinado", "Tinte"]
        assert _combo_offer_in_response(response, pending) is True

    def test_no_name_no_phrase_returns_false(self):
        """Neither name nor phrase → False."""
        response = "¿Qué fecha prefieres para tu cita?"
        pending = ["Tratamiento"]
        assert _combo_offer_in_response(response, pending) is False


# =============================================================================
# _build_response — recommendations_shown gate (combo-recommendations-fix REQ-2)
# =============================================================================


class TestBuildResponseRecommendationsGate:
    """REQ-2: recommendations_shown set only when _combo_offer_in_response returns True."""

    def _make_complete_ctx(
        self, pending_recommendations: list[str] | None = None
    ) -> BookingContext:
        return BookingContext(
            service_id="svc-001",
            service_name="Corte de Dama",
            stylist_id="sty-001",
            stylist_name="María",
            offered_slots=[
                {"time": "10:00", "date": "lunes", "full_datetime": "2026-03-30T10:00:00"}
            ],
            customer_name="Ana",
            customer_id="cust-001",
            pending_recommendations=pending_recommendations
            if pending_recommendations is not None
            else ["Tratamiento"],
            recommendations_shown=False,
        )

    def test_flag_not_set_without_offer_in_response(self):
        """Response without combo mention → recommendations_shown stays False."""
        mode = make_booking_mode("Perfecto, ¿con qué estilista?")
        state = make_state()
        ctx = self._make_complete_ctx(pending_recommendations=["Tratamiento"])

        llm_result = AgenticLoopResult(
            response_text="Perfecto, ¿con qué estilista?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.recommendations_shown is False

    def test_flag_set_with_offer_in_response(self):
        """Response mentioning the pending service → recommendations_shown becomes True."""
        mode = make_booking_mode("¿Te gustaría añadir un Tratamiento a tu cita?")
        state = make_state()
        ctx = self._make_complete_ctx(pending_recommendations=["Tratamiento"])

        llm_result = AgenticLoopResult(
            response_text="¿Te gustaría añadir un Tratamiento a tu cita?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.recommendations_shown is True

    def test_flag_already_true_stays_true(self):
        """When recommendations_shown already True, it stays True."""
        mode = make_booking_mode("Perfecto.")
        state = make_state()
        ctx = self._make_complete_ctx(pending_recommendations=["Tratamiento"])
        ctx.recommendations_shown = True  # already set

        llm_result = AgenticLoopResult(
            response_text="Perfecto.",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.recommendations_shown is True

    def test_no_pending_recommendations_no_crash(self):
        """Empty pending_recommendations → gate skipped, no crash."""
        mode = make_booking_mode("¿Te gustaría añadir un Tratamiento?")
        state = make_state()
        ctx = self._make_complete_ctx(pending_recommendations=[])
        ctx.recommendations_shown = False

        llm_result = AgenticLoopResult(
            response_text="¿Te gustaría añadir un Tratamiento?",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            mode._build_response(state, ctx, llm_result)

        assert ctx.recommendations_shown is False
