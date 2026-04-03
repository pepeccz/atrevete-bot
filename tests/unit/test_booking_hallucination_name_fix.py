"""Unit tests for booking-hallucination-name-fix changes (post-restrictor-cleanup).

Coverage:
- T-05: _detect_stylist_hallucination removed (new: force_stylist_correction via _pre_tool_call)
- T-06: _previous_assistant_asked_for_name removed (new: ctx.name_asked flag from _build_response)
- T-07: name_ask_count field + circuit breaker (FR-03) — still valid
- T-08: Placeholder-name guard in _pre_tool_call (FR-04) — still valid

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import (
    BookingMode,
    _extract_name_from_conversation,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_mode() -> BookingMode:
    """Create a BookingMode with a mocked LLM."""
    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "ok"
    mock_response.tool_calls = []
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return BookingMode(tools=[], llm_client=mock_llm)


def _assistant_msg(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _user_msg(content: str) -> dict:
    return {"role": "user", "content": content}


# =============================================================================
# T-05: _detect_stylist_hallucination removed — new behavior via _pre_tool_call
# =============================================================================


class TestServiceWordWhitelist:
    """T-05: text-scanning hallucination detection is gone; force_stylist_correction
    is now triggered by _pre_tool_call when book() receives an invalid stylist_id."""

    def test_detect_stylist_hallucination_method_gone(self):
        """_detect_stylist_hallucination no longer exists on BookingMode."""
        assert not hasattr(BookingMode, "_detect_stylist_hallucination"), (
            "_detect_stylist_hallucination was removed in restrictor cleanup"
        )

    def test_redact_hallucinated_stylists_method_gone(self):
        """_redact_hallucinated_stylists no longer exists on BookingMode."""
        assert not hasattr(BookingMode, "_redact_hallucinated_stylists"), (
            "_redact_hallucinated_stylists was removed in restrictor cleanup"
        )

    def test_correction_prompt_still_injected_when_force_stylist_correction(self):
        """⚠️ CORRECCIÓN CRÍTICA block still injected when force_stylist_correction=True."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana García", "id": "sty-001"},
                {"name": "María Fernández", "id": "sty-002"},
            ],
            force_stylist_correction=True,
        )
        state = {
            "customer_phone": "+34612345678",
            "messages": [],
            "mode_context": {},
            "current_mode": "BOOKING",
        }
        result = BookingMode._build_dynamic_context(state, ctx)
        assert "CORRECCIÓN CRÍTICA" in result
        assert "Ana García" in result

    def test_force_stylist_correction_context_when_flag_false(self):
        """Correction block absent when force_stylist_correction=False."""
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana García", "id": "sty-001"}],
            force_stylist_correction=False,
        )
        state = {
            "customer_phone": "+34612345678",
            "messages": [],
            "mode_context": {},
            "current_mode": "BOOKING",
        }
        result = BookingMode._build_dynamic_context(state, ctx)
        assert "CORRECCIÓN CRÍTICA" not in result


# =============================================================================
# T-06: _previous_assistant_asked_for_name removed — replaced by ctx.name_asked flag
# =============================================================================


class TestNameAskPatterns:
    """T-06: _previous_assistant_asked_for_name is gone.
    Name-ask detection now uses ctx.name_asked (set by _build_response).
    """

    def test_previous_assistant_asked_for_name_function_gone(self):
        """_previous_assistant_asked_for_name is no longer exported from booking_mode."""
        import agent.modes.booking_mode as bm

        assert not hasattr(bm, "_previous_assistant_asked_for_name"), (
            "_previous_assistant_asked_for_name was removed in restrictor cleanup"
        )

    def test_ctx_name_asked_controls_tier2_extraction(self):
        """When ctx.name_asked=True, bare-name Tier 2 extraction fires."""
        ctx = BookingContext(name_asked=True)
        state = {"messages": []}
        _extract_name_from_conversation(state, "María García", ctx)
        assert ctx.customer_name == "María García"

    def test_ctx_name_asked_false_blocks_tier2_extraction(self):
        """When ctx.name_asked=False, bare-name Tier 2 extraction does NOT fire."""
        ctx = BookingContext(name_asked=False)
        state = {"messages": []}
        _extract_name_from_conversation(state, "María García", ctx)
        assert ctx.customer_name is None

    def test_tier1_intro_always_fires_regardless_of_name_asked(self):
        """Tier 1 ('me llamo X') always fires even when ctx.name_asked=False."""
        ctx = BookingContext(name_asked=False)
        state = {"messages": []}
        _extract_name_from_conversation(state, "Me llamo Ana Torres", ctx)
        assert ctx.customer_name == "Ana Torres"


# =============================================================================
# T-07: name_ask_count field + circuit breaker
# =============================================================================


class TestNameAskCount:
    """FR-03: name_ask_count circuit breaker."""

    def test_name_ask_count_init(self):
        """BookingContext.name_ask_count starts at 0."""
        ctx = BookingContext()
        assert ctx.name_ask_count == 0

    def test_reset_transient_resets_count(self):
        """reset_transient() sets name_ask_count back to 0."""
        ctx = BookingContext(
            service_name="Corte",
            stylist_id="sty-1",
            offered_slots=[{"time": "10:00"}],
        )
        ctx.name_ask_count = 2
        ctx.reset_transient()
        assert ctx.name_ask_count == 0

    def test_missing_summary_normal_below_threshold(self):
        """name_ask_count=2 → plain 'nombre' in missing summary (no degradation)."""
        ctx = BookingContext(name_ask_count=2)
        summary = ctx.missing_summary()
        # Should contain plain "nombre" without the degradation warning
        assert "nombre" in summary.lower()
        assert "equipo" not in summary

    def test_missing_summary_degradation_at_threshold(self):
        """name_ask_count=3 → graceful degradation message appears."""
        ctx = BookingContext(name_ask_count=3)
        summary = ctx.missing_summary()
        # Should contain the graceful degradation message
        assert "equipo" in summary

    def test_missing_summary_degradation_above_threshold(self):
        """name_ask_count=5 (>3) → degradation message still appears."""
        ctx = BookingContext(name_ask_count=5)
        summary = ctx.missing_summary()
        assert "equipo" in summary

    def test_missing_summary_degradation_manage_customer_failures(self):
        """manage_customer_failure_count >= 2 also triggers degradation (existing logic)."""
        ctx = BookingContext(manage_customer_failure_count=2)
        summary = ctx.missing_summary()
        # Original degradation message OR new message — both contain warning
        assert "equipo" in summary or "pedir confirmación verbal" in summary

    def test_extract_name_increments_count_when_bot_asked(self):
        """_extract_name_from_conversation increments name_ask_count when ctx.name_asked=True."""
        ctx = BookingContext(name_asked=True)  # flag set by _build_response
        state = {"messages": []}
        # User message that won't match any name pattern
        _extract_name_from_conversation(state, "ok", ctx)

        # Bot asked (via flag), extraction failed → counter incremented
        assert ctx.name_ask_count == 1

    def test_extract_name_does_not_increment_when_bot_did_not_ask(self):
        """name_ask_count not incremented when ctx.name_asked=False."""
        ctx = BookingContext(name_asked=False)  # bot hasn't asked yet
        state = {"messages": []}
        _extract_name_from_conversation(state, "ok", ctx)

        assert ctx.name_ask_count == 0

    def test_extract_name_does_not_increment_when_name_found(self):
        """name_ask_count NOT incremented when name is successfully extracted."""
        ctx = BookingContext(name_asked=False)
        state = {"messages": []}
        # User says their name via intro pattern (Tier 1) — always fires
        _extract_name_from_conversation(state, "Me llamo María García", ctx)

        assert ctx.customer_name == "María García"
        assert ctx.name_ask_count == 0

    def test_name_ask_count_serializes_in_mode_context(self):
        """name_ask_count is included in to_mode_context() output."""
        ctx = BookingContext(name_ask_count=2)
        result = ctx.to_mode_context()
        assert result.get("name_ask_count") == 2

    def test_name_ask_count_deserializes_from_mode_context(self):
        """name_ask_count is restored correctly by from_mode_context()."""
        ctx = BookingContext.from_mode_context({"name_ask_count": 3})
        assert ctx.name_ask_count == 3

    def test_name_ask_count_defaults_to_zero_in_from_mode_context(self):
        """Missing name_ask_count in dict defaults to 0 (backward compat)."""
        ctx = BookingContext.from_mode_context({"service_name": "Corte"})
        assert ctx.name_ask_count == 0


# =============================================================================
# T-08: Placeholder-name guard in _pre_tool_call
# =============================================================================


class TestPlaceholderNameGuard:
    """FR-04: manage_customer(create) with placeholder names is rejected."""

    @pytest.mark.asyncio
    async def test_placeholder_name_cliente_rejected(self):
        """first_name='Cliente' → ToolCallRejection with PLACEHOLDER_NAME."""
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {
            "action": "create",
            "phone": "+34600000001",
            "data": {"first_name": "Cliente", "phone": "+34600000001"},
        }
        result = await mode._pre_tool_call("manage_customer", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "PLACEHOLDER_NAME"

    @pytest.mark.asyncio
    async def test_placeholder_name_usuario_rejected(self):
        """first_name='Usuario' → ToolCallRejection with PLACEHOLDER_NAME."""
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {
            "action": "create",
            "phone": "+34600000002",
            "data": {"first_name": "Usuario"},
        }
        result = await mode._pre_tool_call("manage_customer", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "PLACEHOLDER_NAME"

    @pytest.mark.asyncio
    async def test_placeholder_name_case_insensitive(self):
        """Placeholder check is case-insensitive: 'CLIENTE' is also rejected."""
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {
            "action": "create",
            "phone": "+34600000003",
            "data": {"first_name": "CLIENTE"},
        }
        result = await mode._pre_tool_call("manage_customer", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "PLACEHOLDER_NAME"

    @pytest.mark.asyncio
    async def test_placeholder_name_desconocido_rejected(self):
        """first_name='Desconocido' → ToolCallRejection with PLACEHOLDER_NAME."""
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {
            "action": "create",
            "phone": "+34600000004",
            "data": {"first_name": "Desconocido"},
        }
        result = await mode._pre_tool_call("manage_customer", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "PLACEHOLDER_NAME"

    @pytest.mark.asyncio
    async def test_real_name_allowed(self):
        """first_name='Maria' → not a placeholder, call proceeds normally."""
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {
            "action": "create",
            "phone": "+34600000005",
            "data": {"first_name": "Maria", "phone": "+34600000005"},
        }
        result = await mode._pre_tool_call("manage_customer", args)

        # Should NOT be a ToolCallRejection with PLACEHOLDER_NAME
        assert not isinstance(result, ToolCallRejection) or result.error_code != "PLACEHOLDER_NAME"

    @pytest.mark.asyncio
    async def test_stylist_name_as_customer_allowed(self):
        """first_name='Ana' (happens to be a stylist name) → no rejection."""
        mode = _make_mode()
        mode._ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "sty-1"}],
        )
        args = {
            "action": "create",
            "phone": "+34600000006",
            "data": {"first_name": "Ana", "phone": "+34600000006"},
        }
        result = await mode._pre_tool_call("manage_customer", args)

        # "Ana" is a real name, not a placeholder — must pass through
        assert not isinstance(result, ToolCallRejection) or result.error_code != "PLACEHOLDER_NAME"

    @pytest.mark.asyncio
    async def test_placeholder_guard_only_on_create_not_update(self):
        """Guard applies only to action='create', not 'update'."""
        mode = _make_mode()
        mode._ctx = BookingContext(customer_id="cust-existing")
        args = {
            "action": "update",
            "data": {"first_name": "Cliente", "customer_id": "cust-existing"},
        }
        result = await mode._pre_tool_call("manage_customer", args)

        # 'update' action → placeholder guard does NOT fire
        assert not isinstance(result, ToolCallRejection) or result.error_code != "PLACEHOLDER_NAME"

    @pytest.mark.asyncio
    async def test_empty_first_name_not_rejected_by_guard(self):
        """Empty first_name doesn't trigger placeholder guard (other guards may fire)."""
        mode = _make_mode()
        mode._ctx = BookingContext()
        args = {
            "action": "create",
            "phone": "+34600000007",
            "data": {"first_name": "", "phone": "+34600000007"},
        }
        result = await mode._pre_tool_call("manage_customer", args)

        # Empty name → NOT a placeholder rejection (guard requires non-empty match)
        assert not isinstance(result, ToolCallRejection) or result.error_code != "PLACEHOLDER_NAME"
