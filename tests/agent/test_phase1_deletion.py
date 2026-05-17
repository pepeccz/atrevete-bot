"""Phase 1 deletion verification — agent-tools-shared-extraction.

Spec: Domain 1 — Dead Code Removal.

These tests assert that dead code removed in Phase 1 is truly absent.
They are RED before the deletion and GREEN after.

TDD approach for deletion tasks:
- Tests assert ABSENCE of the deleted artifact
- Before deletion: tests FAIL (RED) — the module/endpoint still exists
- After deletion: tests PASS (GREEN) — the module/endpoint is gone
"""

import importlib
import importlib.util
import os
import sys


class TestAvailabilityToolsAbsence:
    """Domain 1 — agent/tools/availability_tools.py must not exist."""

    def test_availability_tools_file_does_not_exist(self):
        """SPEC: agent/tools/availability_tools.py must not be present on disk."""
        # Resolve from package root (two levels up from tests/agent/)
        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        target = os.path.join(root_dir, "agent", "tools", "availability_tools.py")
        assert not os.path.exists(target), (
            f"availability_tools.py still exists at {target} — it must be deleted (Phase 1)"
        )

    def test_availability_tools_not_importable(self):
        """SPEC: agent.tools.availability_tools module must not be importable."""
        # Evict any cached module to get a fresh import attempt
        sys.modules.pop("agent.tools.availability_tools", None)
        spec = importlib.util.find_spec("agent.tools.availability_tools")
        assert spec is None, (
            "agent.tools.availability_tools is still importable — "
            "the module must be deleted (Phase 1)"
        )


class TestCalendarAvailabilityRouteAbsence:
    """Domain 1 — GET /calendar/availability endpoint must not exist in admin.py."""

    def test_admin_py_has_no_calendar_availability_route(self):
        """SPEC: GET /calendar/availability route must not be registered in admin.py."""
        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        admin_py = os.path.join(root_dir, "api", "routes", "admin.py")
        with open(admin_py) as f:
            content = f.read()
        assert '"/calendar/availability"' not in content and "'/calendar/availability'" not in content, (
            'GET /calendar/availability route decorator still present in admin.py — must be deleted (Phase 1)'
        )

    def test_admin_py_has_no_availability_tools_import(self):
        """SPEC: admin.py must not import from agent.tools.availability_tools."""
        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        admin_py = os.path.join(root_dir, "api", "routes", "admin.py")
        with open(admin_py) as f:
            content = f.read()
        assert "availability_tools" not in content, (
            "admin.py still references availability_tools — "
            "the import must be removed along with the route (Phase 1)"
        )


class TestGetAvailabilityFrontendAbsence:
    """Domain 1 — getAvailability must not exist in admin-panel/src/lib/api.ts."""

    def test_api_ts_has_no_get_availability(self):
        """SPEC: getAvailability function must be absent from api.ts."""
        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        api_ts = os.path.join(root_dir, "admin-panel", "src", "lib", "api.ts")
        with open(api_ts) as f:
            content = f.read()
        assert "getAvailability" not in content, (
            "getAvailability is still defined in admin-panel/src/lib/api.ts — "
            "it must be deleted (Phase 1)"
        )
