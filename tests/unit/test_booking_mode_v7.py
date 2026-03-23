"""
Unit tests for agent/modes/booking_mode_v7.py — BookingModeV7 (LLM-driven booking).

Coverage:
- Import and instantiation
- Cancel/escalate detection (with negation)
- Name redaction (module-level functions)
- Dynamic context section builders (module-level functions)
- BookingContextV7 integration (round-trip, readiness, summaries)

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_context_v7 import BookingContextV7
from agent.modes.booking_mode_v7 import (
    BookingModeV7,
    _build_disambiguation_section,
    _build_offered_slots_section,
    _build_recommendations_section,
    _build_stylists_section,
    _contains_name_token,
    _detect_recommendation_decline,
    _normalize_text,
    _redact_name_tokens,
)
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_intent(intent: str = "book", confidence: float = 0.9) -> IntentResult:
    return IntentResult(
        intent=intent, confidence=confidence, raw_input="test", mode_hint="BOOKING"
    )


def make_mock_llm(response_text: str = "¿Qué servicio deseas?") -> AsyncMock:
    """Mock LLM that returns a simple text response with no tool calls."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode_v7(llm_response: str = "¿Qué servicio deseas?") -> BookingModeV7:
    mock_llm = make_mock_llm(llm_response)
    return BookingModeV7(tools=[], llm_client=mock_llm)


def make_state(
    customer_name: str | None = "María",
    customer_id: str | None = "cust-001",
    user_message: str = "quiero reservar",
    mode_context: dict | None = None,
) -> dict:
    """Build a ConversationState for BookingModeV7 tests."""
    state = create_initial_state("conv-v7-001", "+34612345678")
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


class TestBookingModeV7Instantiation:
    def test_can_import_and_create(self):
        mode = make_booking_mode_v7()
        assert mode is not None

    def test_mode_name_is_booking(self):
        mode = make_booking_mode_v7()
        assert mode.mode_name == "BOOKING"


# =============================================================================
# 2. Cancel / Escalate Detection
# =============================================================================


class TestCancelEscalateDetection:
    """Tests for _check_special_intents fast path."""

    def test_cancel_phrase_transitions_to_general(self):
        mode = make_booking_mode_v7()
        state = make_state(user_message="cancelar mi cita")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "cancelar mi cita", intent)

        assert result is not None
        assert result["current_mode"] == "GENERAL"

    def test_negation_does_not_cancel(self):
        """'no quiero cancelar' should NOT trigger cancellation."""
        mode = make_booking_mode_v7()
        state = make_state(user_message="no quiero cancelar")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "no quiero cancelar", intent)

        assert result is None  # No special intent — continues normal flow

    def test_escalate_phrase_transitions_to_escalation(self):
        mode = make_booking_mode_v7()
        state = make_state(user_message="necesito hablar con alguien")
        intent = make_intent("book")

        result = mode._check_special_intents(
            state, "necesito hablar con alguien", intent
        )

        assert result is not None
        assert result["current_mode"] == "ESCALATION"

    def test_cancel_intent_from_router_transitions(self):
        """Cancel intent from router (not phrase) should also transition."""
        mode = make_booking_mode_v7()
        state = make_state(user_message="ya no quiero")
        intent = make_intent("cancel")

        result = mode._check_special_intents(state, "ya no quiero", intent)

        assert result is not None
        assert result["current_mode"] == "GENERAL"

    def test_escalate_intent_from_router_transitions(self):
        mode = make_booking_mode_v7()
        state = make_state(user_message="ayuda")
        intent = make_intent("escalate")

        result = mode._check_special_intents(state, "ayuda", intent)

        assert result is not None
        assert result["current_mode"] == "ESCALATION"

    def test_normal_message_returns_none(self):
        mode = make_booking_mode_v7()
        state = make_state(user_message="quiero un corte de pelo")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "quiero un corte de pelo", intent)

        assert result is None

    def test_cancel_sets_last_node_and_clears_user_message(self):
        mode = make_booking_mode_v7()
        state = make_state(user_message="cancelar")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "cancelar", intent)

        assert result is not None
        assert result["last_node"] == "booking"
        assert result["user_message"] is None

    def test_continuemos_negates_cancel(self):
        """'continuemos' is a negation token — should not cancel."""
        mode = make_booking_mode_v7()
        state = make_state(user_message="no quiero cancelar, continuemos")
        intent = make_intent("book")

        result = mode._check_special_intents(
            state, "no quiero cancelar, continuemos", intent
        )

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
        mode = make_booking_mode_v7()
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
        result = _redact_name_tokens(
            "Hola María José, tu cita está lista.", "María José"
        )
        assert "María" not in result
        assert "José" not in result
        assert "lista" in result

    def test_redact_name_tokens_no_match_unchanged(self):
        original = "Tu cita está confirmada."
        result = _redact_name_tokens(original, "Carlos")
        assert result == original

    def test_redact_names_on_mode_instance(self):
        """_redact_names method on BookingModeV7 uses state customer names."""
        mode = make_booking_mode_v7()
        state = make_state(customer_name="Laura")
        text = "Perfecto Laura, ya tienes tu cita."

        result = mode._redact_names(state, text)

        assert "Laura" not in result
        assert "cita" in result

    def test_redact_names_no_name_in_state_unchanged(self):
        mode = make_booking_mode_v7()
        state = make_state(customer_name=None)
        text = "Tu cita está lista."

        result = mode._redact_names(state, text)

        assert result == text


# =============================================================================
# 4. Dynamic Context Section Builders
# =============================================================================


class TestBuildDisambiguationSection:
    def test_with_pending_clarification(self):
        ctx = BookingContextV7(
            pending_clarification={
                "axis": "audience",
                "question_hint": "¿Para quién es?",
                "options": [
                    {"value": "adult_female", "label": "Mujer adulta"},
                    {"value": "adult_male", "label": "Hombre adulto"},
                ],
            }
        )

        result = _build_disambiguation_section(ctx)

        assert "CLARIFICACIÓN PENDIENTE" in result
        assert "¿Para quién es?" in result
        assert "Mujer adulta" in result

    def test_empty_when_no_disambiguation(self):
        ctx = BookingContextV7()
        result = _build_disambiguation_section(ctx)
        assert result == ""

    def test_renders_empty_after_pre_resolver_cleared_clarification(self):
        """After resolve_pending_clarification clears pending_clarification, renders empty."""
        ctx = BookingContextV7(
            service_audience_hint="adult_female",
            pending_clarification=None,  # Pre-resolver already cleared it
        )

        result = _build_disambiguation_section(ctx)

        assert result == ""

    def test_renders_pending_when_not_auto_resolved(self):
        """When hint doesn't match (pre-resolver returned False), renders pending options."""
        ctx = BookingContextV7(
            service_audience_hint="baby",
            pending_clarification={
                "axis": "audience",
                "question_hint": "¿Para quién es?",
                "options": [
                    {"value": "adult_female", "label": "Mujer adulta"},
                    {"value": "adult_male", "label": "Hombre adulto"},
                ],
            },
        )

        result = _build_disambiguation_section(ctx)

        assert "CLARIFICACIÓN PENDIENTE (audience)" in result
        assert "Mujer adulta" in result
        assert "Hombre adulto" in result
        assert "CLARIFICACIÓN RESUELTA" not in result

    def test_candidate_services_shown(self):
        ctx = BookingContextV7(
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
        ctx = BookingContextV7(
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
        ctx = BookingContextV7()
        result = _build_stylists_section(ctx)
        assert result == ""

    def test_soonest_slot_shown(self):
        ctx = BookingContextV7(
            prefetched_stylists=[{"name": "Ana", "next_slot_summary": "Hoy 15:00"}],
            soonest_any_slot="Hoy 15:00",
        )

        result = _build_stylists_section(ctx)

        assert "Cualquier profesional disponible" in result
        assert "Hoy 15:00" in result

    def test_recurrent_stylist_hint_shown(self):
        ctx = BookingContextV7(
            prefetched_stylists=[{"name": "Ana", "next_slot_summary": "Mañana 9:00"}],
            recurrent_stylist_hint="Ana",
        )

        result = _build_stylists_section(ctx)

        assert "Estilista habitual" in result
        assert "Ana" in result


class TestBuildOfferedSlotsSection:
    def test_with_offered_slots(self):
        ctx = BookingContextV7(
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
        ctx = BookingContextV7()
        result = _build_offered_slots_section(ctx)
        assert result == ""

    def test_slot_without_stylist_name(self):
        ctx = BookingContextV7(
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
# 5. BookingContextV7 Integration
# =============================================================================


class TestBookingContextV7RoundTrip:
    def test_from_mode_context_to_mode_context_roundtrip(self):
        original = BookingContextV7(
            service_id="svc-001",
            service_name="Corte señora",
            stylist_id="sty-001",
            stylist_name="Ana",
            customer_name="María",
            customer_id="cust-001",
        )

        serialized = original.to_mode_context()
        restored = BookingContextV7.from_mode_context(serialized)

        assert restored.service_id == "svc-001"
        assert restored.service_name == "Corte señora"
        assert restored.stylist_id == "sty-001"
        assert restored.stylist_name == "Ana"
        assert restored.customer_name == "María"
        assert restored.customer_id == "cust-001"

    def test_from_mode_context_ignores_unknown_keys(self):
        data = {"service_id": "svc-001", "unknown_field": "should_be_ignored"}
        ctx = BookingContextV7.from_mode_context(data)
        assert ctx.service_id == "svc-001"
        assert not hasattr(ctx, "unknown_field") or ctx.__dict__.get("unknown_field") is None

    def test_to_mode_context_excludes_none_and_empty(self):
        ctx = BookingContextV7(service_id="svc-001")
        serialized = ctx.to_mode_context()
        assert "service_id" in serialized
        assert "stylist_id" not in serialized  # None → excluded
        assert "candidate_services" not in serialized  # [] → excluded

    def test_to_mode_context_excludes_private_fields(self):
        ctx = BookingContextV7(_booking_completed=True)
        serialized = ctx.to_mode_context()
        assert "_booking_completed" not in serialized


class TestBookingContextV7Readiness:
    def test_is_ready_to_book_all_fields(self):
        ctx = BookingContextV7(
            service_id="svc-001",
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-23T10:00:00", "date": "2026-03-23"},
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is True

    def test_is_ready_to_book_with_selected_services(self):
        """selected_services satisfies the service requirement."""
        ctx = BookingContextV7(
            selected_services=["Corte señora"],
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-23T10:00:00"},
            customer_id="cust-001",
        )
        assert ctx.is_ready_to_book() is True

    def test_not_ready_missing_service(self):
        ctx = BookingContextV7(
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-23T10:00:00"},
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is False

    def test_not_ready_missing_stylist(self):
        ctx = BookingContextV7(
            service_id="svc-001",
            selected_slot={"start_time": "2026-03-23T10:00:00"},
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is False

    def test_not_ready_missing_slot(self):
        ctx = BookingContextV7(
            service_id="svc-001",
            stylist_id="sty-001",
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is False

    def test_not_ready_slot_without_start_time(self):
        ctx = BookingContextV7(
            service_id="svc-001",
            stylist_id="sty-001",
            selected_slot={"date": "2026-03-23"},  # Missing start_time
            customer_name="María",
        )
        assert ctx.is_ready_to_book() is False

    def test_not_ready_missing_customer(self):
        ctx = BookingContextV7(
            service_id="svc-001",
            stylist_id="sty-001",
            selected_slot={"start_time": "2026-03-23T10:00:00"},
        )
        assert ctx.is_ready_to_book() is False


class TestBookingContextV7Summaries:
    def test_collected_summary_shows_populated_fields(self):
        ctx = BookingContextV7(
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
        ctx = BookingContextV7()
        summary = ctx.collected_summary()
        assert "ningún dato recogido" in summary

    def test_collected_summary_with_slot(self):
        ctx = BookingContextV7(
            selected_slot={"date": "2026-03-23", "time": "10:00"},
        )
        summary = ctx.collected_summary()
        assert "10:00" in summary

    def test_missing_summary_shows_missing_fields(self):
        ctx = BookingContextV7()
        summary = ctx.missing_summary()
        assert "servicio" in summary.lower()
        assert "estilista" in summary.lower()
        assert "fecha/hora" in summary.lower()
        assert "nombre" in summary.lower()

    def test_missing_summary_all_complete(self):
        ctx = BookingContextV7(
            service_name="Corte",
            stylist_id="sty-001",
            offered_slots=[{"time": "10:00", "date": "2026-03-23"}],
            customer_name="María",
        )
        summary = ctx.missing_summary()
        assert "completos" in summary.lower()

    def test_missing_summary_partial(self):
        ctx = BookingContextV7(
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
        mode = make_booking_mode_v7()
        ctx = BookingContextV7()
        state = make_state(customer_name="Laura", customer_id="cust-100")

        BookingModeV7._resolve_customer_from_state(state, ctx)

        assert ctx.customer_name == "Laura"
        assert ctx.customer_id == "cust-100"

    def test_resolve_customer_does_not_overwrite_existing(self):
        ctx = BookingContextV7(customer_name="Existing", customer_id="existing-id")
        state = make_state(customer_name="Laura", customer_id="cust-100")

        BookingModeV7._resolve_customer_from_state(state, ctx)

        assert ctx.customer_name == "Existing"
        assert ctx.customer_id == "existing-id"

    def test_resolve_audience_hint_from_mode_context(self):
        ctx = BookingContextV7()
        state = make_state()
        state["mode_context"] = {"service_audience_hint": "adult_female"}

        BookingModeV7._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_female"

    def test_resolve_audience_hint_does_not_overwrite(self):
        ctx = BookingContextV7(service_audience_hint="adult_male")
        state = make_state()
        state["mode_context"] = {"service_audience_hint": "adult_female"}

        BookingModeV7._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_male"


# =============================================================================
# 13. Pre-tool-call: customer_id injection gate
# =============================================================================


class TestPreToolCallCustomerIdInjection:
    """Verify that _pre_tool_call always injects real customer_id for book()."""

    @pytest.mark.asyncio
    async def test_injects_real_customer_id_from_context(self):
        """When ctx has customer_id, it overwrites whatever the LLM passed."""
        mode = make_booking_mode_v7()
        mode._ctx = BookingContextV7(
            customer_id="550e8400-e29b-41d4-a716-446655440000"
        )
        tool_args = {
            "customer_id": "FAKE-LLM-HALLUCINATED-UUID",
            "services": ["Corte de Caballero"],
            "first_name": "Pepe",
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert result["customer_id"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_injects_sentinel_when_no_customer_id(self):
        """When ctx has no customer_id, inject sentinel that fails BookSchema validation."""
        mode = make_booking_mode_v7()
        mode._ctx = BookingContextV7()  # No customer_id
        tool_args = {
            "customer_id": "FAKE-UUID",
            "services": ["Corte de Caballero"],
            "first_name": "Pepe",
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert result["customer_id"] == "ERROR:llama_a_manage_customer_primero"

    @pytest.mark.asyncio
    async def test_injects_sentinel_when_no_ctx(self):
        """When _ctx is None (edge case), inject sentinel."""
        mode = make_booking_mode_v7()
        mode._ctx = None
        tool_args = {
            "customer_id": "FAKE-UUID",
            "services": ["Corte de Caballero"],
            "first_name": "Pepe",
        }

        result = await mode._pre_tool_call("book", tool_args)

        assert result["customer_id"] == "ERROR:llama_a_manage_customer_primero"

    @pytest.mark.asyncio
    async def test_non_book_tool_passes_through(self):
        """Non-book tools should not be intercepted."""
        mode = make_booking_mode_v7()
        mode._ctx = BookingContextV7()
        tool_args = {"query": "horarios"}

        result = await mode._pre_tool_call("query_info", tool_args)

        assert result == {"query": "horarios"}
        assert "customer_id" not in result

    @pytest.mark.asyncio
    async def test_customer_id_injection_with_slot_index_resolution(self):
        """customer_id injection AND slot_index resolution work together."""
        mode = make_booking_mode_v7()
        mode._ctx = BookingContextV7(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
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
        ctx = BookingContextV7(
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
        ctx = BookingContextV7(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=True,
        )

        assert _build_recommendations_section(ctx) == ""

    def test_empty_when_already_shown(self):
        """Already shown once → empty string (don't repeat)."""
        ctx = BookingContextV7(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=False,
        )

        assert _build_recommendations_section(ctx) == ""

    def test_empty_when_no_recommendations(self):
        """No pending recommendations → empty string."""
        ctx = BookingContextV7()

        assert _build_recommendations_section(ctx) == ""


# =============================================================================
# 15. Combo Recommendations — _detect_recommendation_decline (Phase 4)
# =============================================================================


class TestDetectRecommendationDecline:
    """Test _detect_recommendation_decline add-on decline detection."""

    def test_detects_no_gracias(self):
        """'no gracias' should trigger decline when recommendations shown."""
        ctx = BookingContextV7(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=False,
        )

        assert _detect_recommendation_decline("no gracias, solo eso", ctx) is True
        assert ctx.recommendations_declined is True

    def test_detects_solo_eso(self):
        """'solo eso' should trigger decline."""
        ctx = BookingContextV7(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
        )

        assert _detect_recommendation_decline("solo eso", ctx) is True
        assert ctx.recommendations_declined is True

    def test_ignores_before_shown(self):
        """Should not detect decline before recommendations are shown."""
        ctx = BookingContextV7(
            pending_recommendations=["Hidratación"],
            recommendations_shown=False,
        )

        assert _detect_recommendation_decline("no gracias", ctx) is False
        assert ctx.recommendations_declined is False

    def test_ignores_when_no_recommendations(self):
        """No pending recommendations → no decline detection."""
        ctx = BookingContextV7()

        assert _detect_recommendation_decline("no gracias", ctx) is False

    def test_ignores_when_already_declined(self):
        """Already declined → don't re-process."""
        ctx = BookingContextV7(
            pending_recommendations=["Hidratación"],
            recommendations_shown=True,
            recommendations_declined=True,
        )

        assert _detect_recommendation_decline("no gracias", ctx) is False

    def test_non_decline_message_returns_false(self):
        """Normal booking message should not trigger decline."""
        ctx = BookingContextV7(
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
        mode = make_booking_mode_v7()
        state = make_state(user_message="no gracias")
        intent = make_intent("book")

        result = mode._check_special_intents(state, "no gracias", intent)

        assert result is None  # No cancel — normal flow continues
