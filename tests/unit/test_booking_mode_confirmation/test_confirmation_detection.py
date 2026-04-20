"""
Unit tests for the affirmation/negation detection hook wired into
BookingModeNode.handle() — Change 1 (W4 fix).

The hook runs BEFORE the agentic loop: when _confirmation_shown=True and
confirmed=False, it calls is_affirmation()/is_negation() to deterministically
flip booking_context["confirmed"] without waiting for the LLM.

REQs covered: REQ-35 (W4 close)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(user_message: str, booking_context: dict) -> dict:
    """Build a minimal ConversationState for testing the handle() hook."""
    return {
        "conversation_id": "test-conv-001",
        "current_mode": "BOOKING",
        "booking_context": booking_context,
        "mode_context": {},
        "messages": [
            {"role": "user", "content": user_message, "timestamp": "2026-04-20T00:00:00Z"}
        ],
        "user_message": user_message,
        "customer_phone": None,
        "customer_name": None,
        "customer_memories": None,
    }


def _make_booking_context_with_summary_shown(**overrides) -> dict:
    """BookingContext where summary has been shown but not yet confirmed."""
    base = {
        "_booking_completed": False,
        "confirmed": False,
        "_confirmation_shown": True,
        "last_services": ["Corte"],
        "last_stylist": "Ana",
        "selected_slot": {"start": "2026-04-21T10:00:00"},
        "customer_name": "María García",
        "notes_state": "skipped",
        "add_more_asked": True,
        "pending_disambiguations": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfirmationDetection:
    """
    Verify the pre-loop affirmation/negation hook in BookingModeNode.handle().

    The hook mutates an INTERNAL COPY of booking_context inside handle().
    The mutated copy is returned in the state updates dict under "booking_context".
    Tests retrieve the returned booking_context from handle()'s return value.
    """

    def _run_handle(self, user_message: str, booking_context: dict) -> dict:
        """
        Run BookingModeNode.handle() with a patched agentic loop.

        Returns the booking_context from handle()'s return value — this is the
        INTERNAL COPY that was mutated by the pre-loop affirmation/negation hook.

        Note: handle() does dict(state.get("booking_context") or {}) so mutations
        go to the copy, not the original. The copy is then returned as
        updates["booking_context"] (full-replace reducer).
        """
        import asyncio

        from agent.modes.base import AgenticLoopResult
        from agent.modes.booking_mode import BookingModeNode

        async def _fake_invoke(messages, tools, tool_choice, state=None):
            return AgenticLoopResult(response_text="ok")

        state = _make_state(user_message, booking_context)

        async def _run() -> dict:
            with (
                patch.object(BookingModeNode, "_invoke_create_agent", side_effect=_fake_invoke),
                patch.object(
                    BookingModeNode,
                    "_load_stylists_by_category",
                    new=AsyncMock(return_value={}),
                ),
                patch.object(
                    BookingModeNode,
                    "_load_service_names",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    BookingModeNode,
                    "_build_messages",
                    new=AsyncMock(return_value=[]),
                ),
                patch(
                    "agent.modes.booking_mode.get_booking_config",
                    new=AsyncMock(
                        return_value=MagicMock(tool_choice_policy=MagicMock(value="never_force"))
                    ),
                ),
            ):
                node = BookingModeNode.__new__(BookingModeNode)
                node.llm = MagicMock()
                updates = await node.handle(state, intent=None)
                return updates

        updates = asyncio.get_event_loop().run_until_complete(_run())
        # handle() returns the mutated copy under "booking_context"
        return updates.get("booking_context", booking_context)

    def test_dale_sets_confirmed_true_when_summary_shown(self) -> None:
        """
        Given: _confirmation_shown=True, confirmed=False
        When: user sends "dale"
        Then: booking_context["confirmed"] is True (W4 fix)
        """
        bc = _make_booking_context_with_summary_shown()
        result = self._run_handle("dale", bc)
        assert result["confirmed"] is True, (
            "REGRESSION W4: 'dale' with _confirmation_shown=True must set confirmed=True. "
            f"Got confirmed={result.get('confirmed')!r}"
        )

    def test_si_sets_confirmed_true(self) -> None:
        """
        Given: _confirmation_shown=True, confirmed=False
        When: user sends "sí"
        Then: booking_context["confirmed"] is True
        """
        bc = _make_booking_context_with_summary_shown()
        result = self._run_handle("sí", bc)
        assert (
            result["confirmed"] is True
        ), f"'sí' must set confirmed=True. Got confirmed={result.get('confirmed')!r}"

    def test_ya_esta_leaves_confirmed_false_and_clears_summary(self) -> None:
        """
        Given: _confirmation_shown=True, confirmed=False
        When: user sends "ya está" (a canonical negation phrase — "I want to change something")
        Then: confirmed remains False AND _confirmation_shown is cleared (False)

        Note: is_negation() uses the "¿algo más?" negation phrases (ya/ya está/nada/etc.).
        Plain "no" is NOT in the negation list — it's ambiguous and handled by the LLM.
        """
        bc = _make_booking_context_with_summary_shown()
        result = self._run_handle("ya esta", bc)
        assert (
            result["confirmed"] is False
        ), f"Negation must leave confirmed=False. Got {result.get('confirmed')!r}"
        assert result.get("_confirmation_shown") is False, (
            "Negation must clear _confirmation_shown so a new summary can be shown. "
            f"Got _confirmation_shown={result.get('_confirmation_shown')!r}"
        )

    def test_unrelated_message_does_not_flip_confirmed(self) -> None:
        """
        Given: _confirmation_shown=True, confirmed=False
        When: user sends an unrelated message ("¿cuánto cuesta?")
        Then: confirmed remains False AND _confirmation_shown stays True
        (the LLM handles it in the agentic loop)
        """
        bc = _make_booking_context_with_summary_shown()
        result = self._run_handle("¿cuánto cuesta?", bc)
        assert result["confirmed"] is False, (
            "Unrelated message must NOT flip confirmed. "
            f"Got confirmed={result.get('confirmed')!r}"
        )
        assert result.get("_confirmation_shown") is True, (
            "Unrelated message must NOT clear _confirmation_shown. "
            f"Got _confirmation_shown={result.get('_confirmation_shown')!r}"
        )

    def test_no_hook_fires_when_confirmation_not_shown(self) -> None:
        """
        Given: _confirmation_shown=False (summary not yet shown)
        When: user sends "dale"
        Then: confirmed stays False (hook only fires when summary is shown)
        """
        bc = _make_booking_context_with_summary_shown(_confirmation_shown=False)
        result = self._run_handle("dale", bc)
        assert result["confirmed"] is False, (
            "Hook must NOT set confirmed=True when _confirmation_shown=False. "
            f"Got confirmed={result.get('confirmed')!r}"
        )

    def test_hook_skipped_when_already_confirmed(self) -> None:
        """
        Given: _confirmation_shown=True, confirmed=True (already confirmed)
        When: user sends any message
        Then: hook does not re-evaluate (condition is not triggered)
        """
        bc = _make_booking_context_with_summary_shown(confirmed=True)
        result = self._run_handle("dale", bc)
        # confirmed was already True — must remain True
        assert result["confirmed"] is True, (
            "confirmed=True must not be overwritten by hook. "
            f"Got confirmed={result.get('confirmed')!r}"
        )
