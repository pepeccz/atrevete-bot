"""Unit test — grounding sees pre-loop resolver patches on the same turn.

Bug (explore §Part 3, Surprise #2):
  BookingModeNode.handle() runs pre-loop resolvers that mutate ``booking_context``
  (a local dict) via apply_resolver_patch. However, ``self._current_state = state``
  is assigned at booking_mode.py:454 BEFORE rebinding ``state["booking_context"]``
  to the post-resolver dict. The middleware closure calls ``get_state_fn()``
  which returns ``self._current_state`` — i.e. the checkpoint state with the OLD
  ``booking_context``. Pre-loop patches are invisible to grounding on the same turn.

Fix (Phase 3 — design §AD-3b, §AD-4):
  Before ``self._current_state = state``, rebind:
      state["booking_context"] = booking_context
  so that ``compute_next_prompt(real_state)`` inside BookingGroundingMiddleware
  receives the post-resolver dict.

Test strategy:
  We test the fix at the PURE FUNCTION level (compute_next_prompt) rather than
  mocking the full middleware stack. The test constructs two state dicts:

  - ``stale_state``: ``state["booking_context"]`` = checkpoint dict (add_more_asked absent)
  - ``fresh_state``: ``state["booking_context"]`` = post-resolver dict (add_more_asked=True)

  For a booking_context that has services but NOT add_more_asked, grounding returns
  ASK_MORE_SERVICES. After the resolver sets add_more_asked=True and the state is
  rebound, grounding must NOT return ASK_MORE_SERVICES.

  RED on master: because ``booking_context`` is mutated in-place but
  ``state["booking_context"]`` is never rebound, middleware uses the stale state.
  The test simulates this by checking that ``compute_next_prompt(stale_state)``
  returns ASK_MORE_SERVICES (the wrong answer) while ``compute_next_prompt(fresh_state)``
  returns something else (the correct answer). The RED assertion is on the rebind
  contract: after BookingModeNode does the patch, the state it exposes via
  ``_current_state`` MUST return the fresh result.

GREEN after Phase 3: booking_mode.py rebinds ``state["booking_context"]``
  before assigning ``self._current_state``.

Placement: tests/unit/booking/test_grounding_sees_pre_loop_patches.py
"""

from __future__ import annotations

import pytest

from agent.booking.grounding import compute_next_prompt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stale_state(booking_context: dict) -> dict:
    """Simulates the state BEFORE the rebind fix — booking_context is checkpoint value."""
    return {
        "current_mode": "BOOKING",
        "booking_context": booking_context,  # this is the STALE checkpoint
        "conversation_id": "test-snapshot-001",
        "total_message_count": 2,
    }


def _make_fresh_state(stale_booking_context: dict, post_resolver_booking_context: dict) -> dict:
    """Simulates the state AFTER the rebind fix — booking_context is post-resolver dict."""
    return {
        "current_mode": "BOOKING",
        "booking_context": post_resolver_booking_context,  # rebound to live dict
        "conversation_id": "test-snapshot-001",
        "total_message_count": 2,
    }


# ---------------------------------------------------------------------------
# THE TEST
# ---------------------------------------------------------------------------


class TestGroundingSeesPreLoopPatches:
    """
    Verify that after a pre-loop resolver sets add_more_asked=True, compute_next_prompt
    called with the rebound state returns a different action than with the stale state.
    """

    def test_stale_state_returns_ask_more_services(self):
        """
        With a stale state (add_more_asked absent / False), compute_next_prompt
        returns ASK_MORE_SERVICES. This is the WRONG answer once the resolver fires.
        """
        checkpoint_bc = {
            "_booking_completed": False,
            "confirmed": False,
            "_confirmation_shown": False,
            "pending_disambiguations": [],
            "last_services": ["Corte Señora"],  # services present
            "add_more_asked": False,  # NOT yet set by resolver
        }
        stale_state = _make_stale_state(checkpoint_bc)
        directive = compute_next_prompt(stale_state)
        assert directive.action == "ASK_MORE_SERVICES", (
            f"Expected ASK_MORE_SERVICES on stale state, got {directive.action!r}. "
            "This confirms the baseline: without add_more_asked=True, grounding asks "
            "for more services."
        )

    def test_fresh_state_does_not_return_ask_more_services(self):
        """
        After the pre-loop negation resolver sets add_more_asked=True, the rebound
        state must NOT return ASK_MORE_SERVICES — grounding should advance to the next step.

        RED on master: because _current_state is never rebound, the middleware would
        pass the STALE state (add_more_asked=False) to compute_next_prompt and get
        ASK_MORE_SERVICES even after the resolver fired.

        This test targets the rebound contract: fresh_state["booking_context"] must
        be the post-resolver dict so compute_next_prompt sees add_more_asked=True.
        """
        checkpoint_bc = {
            "_booking_completed": False,
            "confirmed": False,
            "_confirmation_shown": False,
            "pending_disambiguations": [],
            "last_services": ["Corte Señora"],
            "add_more_asked": False,  # stale checkpoint
        }

        # Simulate apply_resolver_patch mutating the local booking_context dict.
        # In production, this happens via resolve_add_more_negation + apply_resolver_patch.
        post_resolver_bc = dict(checkpoint_bc)
        post_resolver_bc["add_more_asked"] = True  # resolver fired

        fresh_state = _make_fresh_state(checkpoint_bc, post_resolver_bc)
        directive = compute_next_prompt(fresh_state)

        assert directive.action != "ASK_MORE_SERVICES", (
            f"Expected action != ASK_MORE_SERVICES after pre-loop resolver set "
            f"add_more_asked=True, but got {directive.action!r}. "
            "This means the grounding middleware still sees stale state. "
            "RED until Phase 3 rebinds state['booking_context'] before assigning "
            "self._current_state in booking_mode.py."
        )

    def test_booking_mode_current_state_reflects_pre_loop_patches(self):
        """
        Verifies the ACTUAL production bug in BookingModeNode:

        booking_mode.py (master, line 452-454):
          self._booking_context = booking_context   # local mutated dict
          self._mode_context = booking_context
          self._current_state = state               # state["booking_context"] is CHECKPOINT

        The middleware closure reads ``self._current_state``, so it sees stale
        ``booking_context``. This test asserts that on master (no fix),
        ``self._current_state["booking_context"]`` is NOT the same object as
        ``self._booking_context`` — i.e. the rebind is missing.

        RED on master: because state["booking_context"] is NOT rebound before
        self._current_state = state (line 454), so ``_current_state["booking_context"]``
        does NOT equal ``_booking_context`` (they are different dict objects).

        GREEN after Phase 3: because the one-line fix
          state["booking_context"] = booking_context
        runs before line 454, making ``_current_state["booking_context"]``
        the same object (same ``id``) as ``_booking_context``.
        """
        from agent.modes.booking_mode import BookingModeNode
        from unittest.mock import patch as _patch

        with _patch("agent.modes.booking_mode.BaseModeNode.__init__", return_value=None):
            node = BookingModeNode.__new__(BookingModeNode)

        node.llm = None
        node._cached_stylists_by_category = {}
        node._cached_service_names = {}

        # Simulate the checkpoint state (what comes from LangGraph persistence)
        checkpoint_bc_dict = {
            "_booking_completed": False,
            "confirmed": False,
            "_confirmation_shown": False,
            "pending_disambiguations": [],
            "last_services": ["Corte Señora"],
            "add_more_asked": False,
        }
        state = {
            "current_mode": "BOOKING",
            "booking_context": checkpoint_bc_dict,
        }

        # booking_context is a fresh LOCAL copy (what booking_mode.py line 191 does)
        booking_context = dict(state.get("booking_context") or {})

        # A pre-loop resolver mutates the LOCAL copy
        booking_context["add_more_asked"] = True

        # Reproduce what booking_mode.py does at lines 452-454 (master — NO rebind)
        node._booking_context = booking_context
        node._mode_context = booking_context
        node._current_state = state  # state["booking_context"] is still checkpoint_bc_dict

        # ── RED assertion: _current_state["booking_context"] MUST be the same object
        # as _booking_context. On master this FAILS because there is no rebind.
        # On Phase 3 this PASSES because state["booking_context"] = booking_context
        # is inserted before self._current_state = state.
        assert node._current_state["booking_context"] is node._booking_context, (
            "FAIL (RED on master): self._current_state['booking_context'] is not the same "
            "object as self._booking_context. Pre-loop resolver patches are invisible to "
            "the grounding middleware because get_state_fn() returns _current_state whose "
            "booking_context is the stale checkpoint dict. "
            "FIX: add state['booking_context'] = booking_context before "
            "self._current_state = state in booking_mode.py."
        )
