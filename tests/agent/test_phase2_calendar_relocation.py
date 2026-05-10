"""Phase 2 — calendar infrastructure relocation tests.

Spec: Domain 2 — shared/calendar_service.py becomes the canonical implementation.
agent/tools/calendar_tools.py becomes a backward-compat reverse shim.

TDD: these tests are RED before the relocation, GREEN after.
"""

import importlib
import importlib.util
import os


class TestSharedCalendarServiceExists:
    """Domain 2 — shared/calendar_service.py must exist with required symbols."""

    def test_shared_calendar_service_importable(self):
        """SPEC: shared.calendar_service must be importable."""
        mod = importlib.import_module("shared.calendar_service")
        assert mod is not None

    def test_shared_calendar_service_exposes_CalendarTools(self):
        """SPEC: CalendarTools must be exported from shared.calendar_service."""
        mod = importlib.import_module("shared.calendar_service")
        assert hasattr(mod, "CalendarTools"), "CalendarTools not found in shared.calendar_service"

    def test_shared_calendar_service_exposes_get_calendar_client(self):
        """SPEC: get_calendar_client must be exported from shared.calendar_service."""
        mod = importlib.import_module("shared.calendar_service")
        assert hasattr(
            mod, "get_calendar_client"
        ), "get_calendar_client not found in shared.calendar_service"

    def test_shared_calendar_service_exposes_fetch_calendar_events_async(self):
        """SPEC: fetch_calendar_events_async must be exported from shared.calendar_service."""
        mod = importlib.import_module("shared.calendar_service")
        assert hasattr(
            mod, "fetch_calendar_events_async"
        ), "fetch_calendar_events_async not found in shared.calendar_service"

    def test_shared_calendar_service_has_all(self):
        """SPEC: shared.calendar_service must define __all__ with required symbols."""
        mod = importlib.import_module("shared.calendar_service")
        assert hasattr(mod, "__all__"), "shared.calendar_service does not define __all__"
        all_names = set(mod.__all__)
        required = {"CalendarTools", "get_calendar_client", "fetch_calendar_events_async"}
        assert required.issubset(all_names), (
            f"__all__ is missing: {required - all_names}"
        )


class TestCalendarToolsReverseShim:
    """Domain 2 — agent/tools/calendar_tools.py must be a thin reverse shim."""

    def test_calendar_tools_still_importable_via_legacy_path(self):
        """SPEC: existing import path still resolves via backward-compat shim."""
        mod = importlib.import_module("agent.tools.calendar_tools")
        assert hasattr(mod, "CalendarTools"), "CalendarTools not found via legacy path"
        assert hasattr(mod, "get_calendar_client"), "get_calendar_client not found via legacy path"
        assert hasattr(
            mod, "fetch_calendar_events_async"
        ), "fetch_calendar_events_async not found via legacy path"

    def test_calendar_tools_shim_contains_no_implementation(self):
        """SPEC: agent/tools/calendar_tools.py must only re-export, not define classes or functions."""
        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        shim_path = os.path.join(root_dir, "agent", "tools", "calendar_tools.py")
        with open(shim_path) as f:
            content = f.read()
        assert "class CalendarTools" not in content, (
            "CalendarTools class defined directly in shim — must be in shared.calendar_service"
        )
        assert "async def fetch_calendar_events_async" not in content, (
            "fetch_calendar_events_async defined directly in shim — must be in shared.calendar_service"
        )
        assert "def get_calendar_client" not in content, (
            "get_calendar_client defined directly in shim — must be in shared.calendar_service"
        )

    def test_calendar_tools_symbols_are_same_objects_as_shared(self):
        """SPEC: symbols imported via legacy path must be the same objects as shared.calendar_service."""
        # Clear any cached imports to force fresh load
        import sys
        for mod_name in list(sys.modules.keys()):
            if mod_name in ("agent.tools.calendar_tools", "shared.calendar_service"):
                del sys.modules[mod_name]

        shim = importlib.import_module("agent.tools.calendar_tools")
        canonical = importlib.import_module("shared.calendar_service")
        assert shim.CalendarTools is canonical.CalendarTools, (
            "CalendarTools via legacy path is not the same object as shared.calendar_service.CalendarTools"
        )
        assert shim.get_calendar_client is canonical.get_calendar_client, (
            "get_calendar_client via legacy path is not the same object"
        )
        assert shim.fetch_calendar_events_async is canonical.fetch_calendar_events_async, (
            "fetch_calendar_events_async via legacy path is not the same object"
        )


class TestAdminImportsFromSharedCalendar:
    """Domain 2 — admin.py must import calendar tools from shared, not agent.tools."""

    def test_admin_py_does_not_import_from_agent_tools_calendar_tools(self):
        """SPEC: admin.py must not contain 'from agent.tools.calendar_tools import'."""
        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        admin_py = os.path.join(root_dir, "api", "routes", "admin.py")
        with open(admin_py) as f:
            content = f.read()
        assert "from agent.tools.calendar_tools" not in content, (
            "admin.py still imports from agent.tools.calendar_tools — must use shared.calendar_service"
        )

    def test_admin_py_imports_from_shared_calendar_service(self):
        """SPEC: admin.py must contain 'from shared.calendar_service import'."""
        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        admin_py = os.path.join(root_dir, "api", "routes", "admin.py")
        with open(admin_py) as f:
            content = f.read()
        assert "from shared.calendar_service import" in content, (
            "admin.py does not import from shared.calendar_service"
        )
