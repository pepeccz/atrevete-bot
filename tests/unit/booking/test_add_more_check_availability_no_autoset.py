"""
B.2.2 [RED] — Assert that _post_tool_result for check_availability does NOT auto-set
add_more_asked on booking_context.

After Phase B.2, lines 628-631 in booking_mode.py are deleted. The only writer
for add_more_asked is the pre-loop negation resolver.

Expected failure on master: add_more_asked is set to True by _post_tool_result
when preferred_date_hint or preferred_stylist_name is present in the context.
"""

from __future__ import annotations

import asyncio


class TestAddMoreCheckAvailabilityNoAutoset:
    """_post_tool_result for check_availability must NOT auto-set add_more_asked."""

    def test_post_tool_result_check_availability_does_not_set_add_more_asked(self):
        """check_availability result must not modify add_more_asked.

        RED on master: booking_mode.py:628-631 auto-sets add_more_asked=True
        when preferred_date_hint or preferred_stylist_name is in mode_context.

        GREEN after B.2.6: those lines are deleted.
        """
        from agent.modes.booking_mode import BookingModeNode

        node = BookingModeNode.__new__(BookingModeNode)

        # booking_context with preferred_date_hint (triggers the auto-set on master)
        booking_context: dict = {
            "preferred_date_hint": "mañana",
            "add_more_asked": False,
            "last_services": ["Corte señora"],
        }
        node._booking_context = booking_context
        node._mode_context = booking_context

        # Simulate check_availability tool result
        result = {"available_slots": [
            {"date": "2026-04-25", "time": "10:00", "stylist_name": "Ana"}
        ]}

        async def _run():
            return await node._post_tool_result("check_availability", {"service_names": ["Corte señora"]}, result)

        asyncio.get_event_loop().run_until_complete(_run())

        # After the call, add_more_asked must still be False
        assert booking_context.get("add_more_asked") is False, (
            "check_availability post-result must NOT set add_more_asked=True. "
            f"add_more_asked={booking_context.get('add_more_asked')!r}. "
            "The auto-set shortcut (lines 628-631) must be deleted in Phase B.2."
        )

    def test_post_tool_result_check_availability_stores_slots(self):
        """check_availability still correctly stores offered_slots after B.2 change."""
        from agent.modes.booking_mode import BookingModeNode

        node = BookingModeNode.__new__(BookingModeNode)
        booking_context: dict = {
            "last_services": ["Corte señora"],
            "add_more_asked": True,  # already set — should not be touched
        }
        node._booking_context = booking_context
        node._mode_context = booking_context

        slots = [{"date": "2026-04-25", "time": "10:00", "stylist_name": "Ana"}]
        result = {"available_slots": slots}

        async def _run():
            return await node._post_tool_result("check_availability", {"service_names": ["Corte señora"]}, result)

        asyncio.get_event_loop().run_until_complete(_run())

        # Slots must be stored
        assert booking_context.get("offered_slots") == slots
        # add_more_asked must remain True (not doubled-written)
        assert booking_context.get("add_more_asked") is True
