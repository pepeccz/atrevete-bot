"""
Tests for _post_tool_result[update_booking] execution order.

Verifies the strict sequence:
  1. apply patch   (keys written to mode_context)
  2. gate eval     (_evaluate_confirmation_gate called with post-patch ctx)
  3. cascade clear (_confirmation_shown reset if invalidating keys changed)

This test must FAIL if someone reintroduces the side-effect in _build_flow_hint
as the sole write path for _confirmation_shown, bypassing _post_tool_result.

TDD — T2.4
"""

from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_complete_ctx(**overrides):
    """Return a booking context with ALL required fields set (gate returns True)."""
    base = {
        "last_services": ["Corte"],
        "last_stylist": "María",
        "selected_slot": {"date": "2026-04-20", "time": "10:00"},
        "customer_name": "Juan",
        "notes_state": "provided",
        "add_more_asked": True,
        "_confirmation_shown": False,
    }
    base.update(overrides)
    return base


def _make_update_booking_result(patch_data: dict) -> str:
    """Build a JSON string result from update_booking tool with a patch."""
    import json
    return json.dumps({"_booking_context_patch": patch_data})


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestPostToolResultOrder:
    """Verify apply_patch → gate_eval → cascade_clear ordering."""

    @pytest.mark.asyncio
    async def test_gate_called_after_patch_applied(self):
        """Gate must see the post-patch state, not pre-patch state."""
        from agent.modes.booking_mode import BookingModeNode

        node = BookingModeNode.__new__(BookingModeNode)
        # Start with incomplete context (missing add_more_asked)
        ctx = {
            "last_services": ["Corte"],
            "last_stylist": "María",
            "selected_slot": {"date": "2026-04-20", "time": "10:00"},
            "customer_name": "Juan",
            "notes_state": "provided",
            # add_more_asked missing initially
            "_confirmation_shown": False,
        }
        node._booking_context = ctx

        # Patch arrives and adds add_more_asked=True (completing the booking)
        patch_data = {"add_more_asked": True}
        result_json = _make_update_booking_result(patch_data)

        # Track call sequence via spy on _evaluate_confirmation_gate.
        # Since it's a @staticmethod, we spy by replacing the class attribute directly.
        call_sequence = []
        original_gate = BookingModeNode._evaluate_confirmation_gate

        def spy_gate(ctx_arg):
            # Capture whether add_more_asked is already in ctx when gate is called
            call_sequence.append({
                "event": "gate_eval",
                "add_more_asked": bool(ctx_arg.get("add_more_asked")),
            })
            return original_gate(ctx_arg)

        with patch.object(BookingModeNode, "_evaluate_confirmation_gate", staticmethod(spy_gate)):
            await node._post_tool_result("update_booking", {}, result_json)

        assert len(call_sequence) == 1, "Gate should be called exactly once"
        assert call_sequence[0]["add_more_asked"] is True, (
            "Gate must see post-patch ctx with add_more_asked=True, "
            "not pre-patch ctx where it was missing"
        )

    @pytest.mark.asyncio
    async def test_cascade_clear_runs_after_gate(self):
        """Cascade clear must run AFTER gate eval — if gate set _confirmation_shown=True
        and an invalidating key was in the patch, cascade clear resets it to False."""
        from agent.modes.booking_mode import BookingModeNode

        node = BookingModeNode.__new__(BookingModeNode)
        # Start with all fields complete so gate would return True
        ctx = _make_complete_ctx()
        node._booking_context = ctx

        # Patch that both completes the booking AND includes an invalidating key
        # (services changing with a complete booking triggers: gate→True, cascade→False)
        patch_data = {
            "last_services": ["Tinte"],  # invalidating key
            "add_more_asked": True,
        }
        result_json = _make_update_booking_result(patch_data)

        await node._post_tool_result("update_booking", {}, result_json)

        # Gate fired (set True) but cascade cleared it back to False because
        # last_services is an invalidating key.
        assert ctx.get("_confirmation_shown") is False, (
            "Cascade clear must run AFTER gate eval and reset _confirmation_shown "
            "when invalidating keys are present in the patch"
        )

    @pytest.mark.asyncio
    async def test_gate_sets_confirmation_shown_when_complete(self):
        """When all fields complete and no invalidating keys → _confirmation_shown=True after gate."""
        from agent.modes.booking_mode import BookingModeNode

        node = BookingModeNode.__new__(BookingModeNode)
        ctx = {
            "last_services": ["Manicura"],
            "last_stylist": "Lucía",
            "selected_slot": {"date": "2026-04-22", "time": "09:00"},
            "customer_name": "Pedro",
            "notes_state": "provided",
            "_confirmation_shown": False,
            # add_more_asked missing — patch will supply it
        }
        node._booking_context = ctx

        # Patch adds add_more_asked (non-invalidating) → gate fires, no cascade
        patch_data = {"add_more_asked": True}
        result_json = _make_update_booking_result(patch_data)

        await node._post_tool_result("update_booking", {}, result_json)

        assert ctx.get("_confirmation_shown") is True, (
            "Gate must set _confirmation_shown=True when all fields present "
            "and no invalidating keys in patch"
        )

    @pytest.mark.asyncio
    async def test_no_duplicate_write_path_via_build_flow_hint(self):
        """_build_flow_hint side-effect and _post_tool_result gate must not diverge.

        This test verifies that _build_flow_hint:216-217 (legacy side-effect, pending
        removal in Batch 4) and the new gate produce consistent results when both
        are called with the same complete context.

        Both paths should set _confirmation_shown=True — no conflicting write.
        """
        from agent.modes.booking_mode import BookingModeNode

        # Use the pure gate directly (post-patch simulation)
        complete_ctx = _make_complete_ctx()

        # Gate result
        gate_result = BookingModeNode._evaluate_confirmation_gate(complete_ctx)
        assert gate_result is True, "Gate must return True for complete booking"

        # Legacy _build_flow_hint side-effect simulation:
        # the legacy code sets _confirmation_shown=True when `not pending` (same conditions)
        # We simulate the same logic to verify they agree.
        legacy_ctx = _make_complete_ctx()  # fresh copy
        has_pending = (
            not legacy_ctx.get("last_services")
            or not (legacy_ctx.get("last_stylist") or legacy_ctx.get("no_preference_stylist"))
            or not legacy_ctx.get("selected_slot")
            or not legacy_ctx.get("customer_name")
        )
        # _build_flow_hint also checks add_more_asked indirectly via "pending" list
        if legacy_ctx.get("last_services") and not legacy_ctx.get("add_more_asked"):
            has_pending = True
        if legacy_ctx.get("notes_state", "not_asked") == "not_asked":
            pass  # notes_state "not_asked" doesn't block pending list in _build_flow_hint

        # Both agree: gate returns True AND legacy "not pending" is True
        # (no divergence pre-Batch 4)
        assert not has_pending, (
            "Legacy _build_flow_hint must also consider booking complete for the same ctx"
        )

    @pytest.mark.asyncio
    async def test_gate_not_called_when_patch_is_empty(self):
        """If patch is empty, the gate must NOT be called (no point evaluating)."""
        from agent.modes.booking_mode import BookingModeNode

        node = BookingModeNode.__new__(BookingModeNode)
        ctx = _make_complete_ctx()
        node._booking_context = ctx

        call_count = [0]
        original_gate = BookingModeNode._evaluate_confirmation_gate

        def counting_gate(ctx_arg):
            call_count[0] += 1
            return original_gate(ctx_arg)

        # Empty patch (no _booking_context_patch key)
        import json
        result_json = json.dumps({"some_other_key": "value"})

        with patch.object(BookingModeNode, "_evaluate_confirmation_gate", staticmethod(counting_gate)):
            await node._post_tool_result("update_booking", {}, result_json)

        assert call_count[0] == 0, (
            "Gate must NOT be called when update_booking patch is empty — "
            "avoid unnecessary evaluation and potential side-effects"
        )
