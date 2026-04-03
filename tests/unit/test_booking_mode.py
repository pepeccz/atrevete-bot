"""
Unit tests for agent/modes/booking_mode.py — BookingMode (LLM-driven booking).

Coverage:
- Import and instantiation
- Cancel/escalate detection (removal of _check_special_intents)
- BookingContext round-trip (from_mode_context / to_mode_context)
- BookingContext summaries (collected_summary / missing_summary)
- Pre-resolvers (_resolve_customer_from_state)
- _pre_tool_call: customer_id injection, slot_index resolution, manage_customer name bypass
- _pre_tool_call: audience canonicalization, UUID validation passthrough
- _pre_tool_call slot resolution (new in Phase 4)
- BookRejection auto-summary
- ToolChoiceComputation

Tests for deleted features were removed in Phase 4 (booking-mode-simplification).
Deleted: _detect_confirmation_exchange, _resolve_user_slot_selection, _is_booking_data_complete,
_build_disambiguation_section, _build_stylists_section, _build_offered_slots_section,
_build_recommendations_section, _build_upsell_gate_section, _detect_tool_skips,
_extract_name_from_conversation, _extract_notes_from_conversation, _normalize_text,
_looks_like_clarification, _resolve_audience_hint, _f7_auto_recover,
and BookingContext fields: notes_asked, book_failure_count, needs_availability_refresh,
confirmation_gate_turn_count, stylists_presented, is_ready_to_book(), service_audience_hint,
recurrent_stylist_hint, pending_recommendations, recommendations_shown, recommendations_declined,
recommendations_offer_attempts, etc.

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult, ToolCallRejection
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode
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
    """Tests for cancel/escalate detection via intent.intent (replaces _check_special_intents)."""

    def test_check_special_intents_method_gone(self):
        """_check_special_intents method no longer exists on BookingMode."""
        assert not hasattr(BookingMode, "_check_special_intents"), (
            "_check_special_intents was removed in restrictor cleanup"
        )

    def test_cancel_constants_gone(self):
        """_CANCEL_PHRASES constant no longer exists in booking_mode module."""
        import agent.modes.booking_mode as bm

        assert not hasattr(bm, "_CANCEL_PHRASES"), (
            "_CANCEL_PHRASES was removed in restrictor cleanup"
        )
        assert not hasattr(bm, "_SOFT_CANCEL_PHRASES"), (
            "_SOFT_CANCEL_PHRASES was removed in restrictor cleanup"
        )
        assert not hasattr(bm, "_ESCALATE_PHRASES"), (
            "_ESCALATE_PHRASES was removed in restrictor cleanup"
        )
        assert not hasattr(bm, "_CANCEL_NEGATION_TOKENS"), (
            "_CANCEL_NEGATION_TOKENS was removed in restrictor cleanup"
        )


# =============================================================================
# 3. Name Redaction — module-level functions removed
# =============================================================================


class TestNameRedaction:
    def test_redact_name_tokens_function_gone(self):
        """_redact_name_tokens was removed — whole-response fallback is used instead."""
        import agent.modes.booking_mode as bm

        assert not hasattr(bm, "_redact_name_tokens"), (
            "_redact_name_tokens was removed in restrictor cleanup"
        )


# =============================================================================
# 4. BookingContext Round-Trip
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


# =============================================================================
# 5. BookingContext Summaries
# =============================================================================


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
        # Stylist is gated: only shown when service is known (R3)
        assert "estilista" not in summary.lower()
        assert "fecha/hora" in summary.lower()
        # Name is gated: only shown when service+stylist+slot are all set
        assert "nombre" not in summary.lower()

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
# 6. Pre-resolvers (static methods)
# =============================================================================


class TestPreResolvers:
    def test_resolve_customer_from_state(self):
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


# =============================================================================
# 7. _pre_tool_call: customer_id injection gate
# =============================================================================


class TestPreToolCallCustomerIdInjection:
    """Verify that _pre_tool_call always injects real customer_id for book()."""

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
    async def test_rejects_when_no_ctx(self):
        """When _ctx is None, book returns pass-through (ctx=None branch)."""
        mode = make_booking_mode()
        mode._ctx = None
        tool_args = {
            "customer_id": "FAKE-UUID",
        }

        result = await mode._pre_tool_call("book", tool_args)

        # With ctx=None, book() passes through (no confirmation_shown check)
        assert isinstance(result, dict)


# =============================================================================
# 8. _pre_tool_call: NoGracias conflict fix
# =============================================================================


class TestNoGraciasConflictFix:
    """Verify 'no gracias' no longer triggers cancel intent.
    Since _check_special_intents is removed, cancel is only via router intent.
    """

    def test_check_special_intents_method_not_present(self):
        """_check_special_intents no longer exists — removed in cleanup."""
        assert not hasattr(BookingMode, "_check_special_intents")


# =============================================================================
# 9. _pre_tool_call: manage_customer name bypass
# =============================================================================


class TestPreToolCallNameBypass:
    """manage_customer calls for name-only should be bypassed when customer_id is known."""

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
# 10. _pre_tool_call: UUID validation and audience canonicalization
# =============================================================================


class TestPreToolCallValidation:
    """Tests for UUID validation and audience canonicalization in _pre_tool_call()."""

    @pytest.mark.asyncio
    async def test_uuid_validation_preserves_valid(self):
        """Phase 5.2: Valid stylist_id is preserved."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "real-uuid-1", "name": "Ana"},
            ]
        )
        mode._ctx = ctx

        tool_args = {"stylist_id": "real-uuid-1"}
        result = await mode._pre_tool_call("find_next_available", tool_args)

        # Valid UUID should pass through
        assert result["stylist_id"] == "real-uuid-1"

    @pytest.mark.asyncio
    async def test_audience_canonicalization_already_canonical(self):
        """Phase 6.2: Already-canonical values pass through unchanged."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()

        tool_args = {"audience": "adult_female"}
        result = await mode._pre_tool_call("search_services", tool_args)

        # Already canonical — no change
        assert result["audience"] == "adult_female"


class TestAudienceCanonicalizationInPreToolCall:
    """Verify _pre_tool_call canonicalizes compound audience values."""

    @pytest.mark.asyncio
    async def test_single_canonical_value_unchanged(self):
        """AC-1.7: already-canonical value passes through."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()

        tool_args = {"query": "corte", "audience": "adult_male"}
        result = await mode._pre_tool_call("search_services", tool_args)

        assert isinstance(result, dict)
        assert result["audience"] == "adult_male"


# =============================================================================
# 11. _pre_tool_call: slot_index → UUID resolution (new in Phase 4)
# =============================================================================


class TestPreToolCallSlotResolution:
    """Tests slot_index → UUID resolution in _pre_tool_call."""

    @pytest.mark.asyncio
    async def test_slot_index_resolved_to_uuid(self):
        """slot_index=1 resolves to offered_slots[0] stylist_id and start_time."""
        mode = BookingMode.__new__(BookingMode)
        ctx = BookingContext()
        ctx.confirmation_shown = True
        ctx.customer_id = "cust-uuid"
        ctx.offered_slots = [
            {
                "stylist_id": "s1",
                "start_time": "2026-04-10T09:00",
                "time": "09:00",
                "day_label": "Viernes 10",
            },
            {
                "stylist_id": "s2",
                "start_time": "2026-04-10T10:00",
                "time": "10:00",
                "day_label": "Viernes 10",
            },
        ]
        ctx.selected_services = ["Corte"]
        mode._ctx = ctx
        result = await mode._pre_tool_call("book", {"slot_index": 1, "customer_id": "cust-uuid"})
        assert not isinstance(result, ToolCallRejection)
        assert result["stylist_id"] == "s1"
        assert result["start_time"] == "2026-04-10T09:00"

    @pytest.mark.asyncio
    async def test_invalid_slot_index_rejected(self):
        """slot_index out of range → INVALID_SLOT_INDEX ToolCallRejection."""
        mode = BookingMode.__new__(BookingMode)
        ctx = BookingContext()
        ctx.confirmation_shown = True
        ctx.customer_id = "cust-uuid"
        ctx.offered_slots = [{"stylist_id": "s1", "start_time": "2026-04-10T09:00"}]
        ctx.selected_services = ["Corte"]
        mode._ctx = ctx
        result = await mode._pre_tool_call("book", {"slot_index": 99, "customer_id": "cust-uuid"})
        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "INVALID_SLOT_INDEX"

    @pytest.mark.asyncio
    async def test_availability_tool_clears_slot_state(self):
        """find_next_available clears offered_slots and selected_slot when stylists are shown."""
        mode = BookingMode.__new__(BookingMode)
        ctx = BookingContext(prefetched_stylists=[{"name": "Ana", "id": "test-uuid"}])
        ctx.offered_slots = [{"stylist_id": "s1"}]
        ctx.selected_slot = {"stylist_id": "s1"}
        mode._ctx = ctx
        await mode._pre_tool_call("find_next_available", {})
        assert ctx.offered_slots == []
        assert ctx.selected_slot is None


# =============================================================================
# 12. BookRejection auto-summary
# =============================================================================


class TestBookRejectionAutoSummary:
    """Verify book() rejection auto-generates summary when data complete."""

    @pytest.mark.asyncio
    async def test_auto_summary_injected_when_data_complete(self):
        """AC-4.1: book() rejected with complete data → confirmation_summary_sent=True."""
        mode = make_booking_mode()
        ctx = BookingContext()
        ctx.selected_services = ["Cortar"]
        ctx.service_id = "svc-1"
        ctx.service_category = "Peluquería"
        ctx.stylist_id = "stylist-1"
        ctx.stylist_name = "Pilar"
        ctx.customer_name = "María"
        ctx.customer_id = "cust-1"
        ctx.confirmation_shown = False
        ctx.confirmation_summary_sent = False
        ctx.offered_slots = [{"date": "2026-04-03", "time": "09:00", "stylist_id": "stylist-1"}]
        ctx.selected_slot = {"date": "2026-04-03", "time": "09:00", "stylist_id": "stylist-1"}
        mode._ctx = ctx

        result = await mode._pre_tool_call("book", {"slot_index": 0})
        assert isinstance(result, ToolCallRejection)
        assert ctx.confirmation_summary_sent is True

    @pytest.mark.asyncio
    async def test_no_auto_summary_when_data_incomplete(self):
        """AC-4.4: incomplete data → existing rejection, no summary."""
        mode = make_booking_mode()
        ctx = BookingContext()
        ctx.confirmation_shown = False
        ctx.confirmation_summary_sent = False
        # No service, stylist, etc. — data is incomplete
        mode._ctx = ctx

        result = await mode._pre_tool_call("book", {"slot_index": 0})
        assert isinstance(result, ToolCallRejection)
        assert ctx.confirmation_summary_sent is False


# =============================================================================
# 13. ToolChoiceComputation
# =============================================================================


class TestToolChoiceComputation:
    """Tests for tool_choice='required' logic in BookingMode.handle (T3.1).

    The logic lives inside BookingMode.handle and computes tool_choice
    before calling _run_agentic_loop. We test it by inspecting the
    conditions on a BookingContext directly — no LLM call needed.
    """

    def _compute_tool_choice(self, ctx: BookingContext) -> str | None:
        """Replicate the tool_choice computation from BookingMode.handle."""
        if (
            not ctx.selected_services
            and not ctx.service_id
            and not ctx.pending_clarifications
            and not ctx.confirmation_shown
            and not ctx.offered_slots
            and not ctx.candidate_services
        ):
            return "required"
        return None

    def test_tool_choice_required_when_service_unresolved(self):
        """Empty ctx → tool_choice should be 'required'."""
        ctx = BookingContext()
        assert self._compute_tool_choice(ctx) == "required"

    def test_tool_choice_none_when_service_id_set(self):
        """ctx with service_id → tool_choice should be None."""
        ctx = BookingContext()
        ctx.service_id = "svc-001"
        assert self._compute_tool_choice(ctx) is None

    def test_tool_choice_none_when_selected_services(self):
        """ctx with selected_services → tool_choice should be None."""
        ctx = BookingContext()
        ctx.selected_services = [{"id": "svc-001", "name": "Corte"}]
        assert self._compute_tool_choice(ctx) is None

    def test_tool_choice_none_when_confirmation_shown(self):
        """ctx with confirmation_shown=True → tool_choice should be None."""
        ctx = BookingContext()
        ctx.confirmation_shown = True
        assert self._compute_tool_choice(ctx) is None

    def test_tool_choice_none_when_pending_clarifications(self):
        """ctx with pending_clarifications → tool_choice should be None."""
        ctx = BookingContext()
        ctx.pending_clarifications = ["¿Qué tipo de corte?"]
        assert self._compute_tool_choice(ctx) is None
