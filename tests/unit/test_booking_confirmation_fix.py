"""
T-43: Architecture guard — booking_context module removed.

Verifies that the old agent.modes.booking_context module no longer exports
format_service_list (or any other function that was removed when the module
was consolidated into booking_mode.py or deleted entirely).

If agent.modes.booking_context still exists as a module, it must NOT export
format_service_list — that helper was removed in the v6.0 simplification.
"""

from __future__ import annotations

import importlib
import sys


class TestBookingContextModuleRemoved:
    """T-43: booking_context module either gone or no longer exports format_service_list."""

    def test_no_format_service_list_from_booking_context(self):
        """format_service_list must NOT be importable from agent.modes.booking_context.

        The module was deleted (or gutted) in the v6.0 mode-based architecture.
        Importing format_service_list from it must raise ImportError or AttributeError.
        """
        try:
            module = importlib.import_module("agent.modes.booking_context")
        except ImportError:
            # Module deleted entirely — that's the expected outcome
            return

        # Module still exists (maybe as a stub) — ensure format_service_list is gone
        assert not hasattr(module, "format_service_list"), (
            "format_service_list found in agent.modes.booking_context — "
            "this function was removed in the v6.0 architecture refactor. "
            "BookingContext no longer has a format_service_list helper."
        )

    def test_booking_context_not_in_sys_modules_or_does_not_have_format_service_list(self):
        """Double-check via sys.modules that format_service_list is absent."""
        module_name = "agent.modes.booking_context"

        # If the module was never loaded, there's nothing to check
        if module_name not in sys.modules:
            try:
                mod = importlib.import_module(module_name)
            except ImportError:
                # Module gone — pass
                return
        else:
            mod = sys.modules[module_name]

        assert not hasattr(mod, "format_service_list"), (
            f"format_service_list exists on {module_name} — must be removed"
        )
