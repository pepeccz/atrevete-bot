"""Phase 3 — forward shim tests.

Spec: Domain 3 — shared/ must expose all symbols admin.py consumes from agent.*.
Each shim module must use explicit re-exports and define __all__.
api/ must have zero direct agent imports after Phase 3.

TDD: tests are RED before shim creation, GREEN after.
"""

import importlib
import os

# ---------------------------------------------------------------------------
# shared/availability_service.py shim
# ---------------------------------------------------------------------------


class TestAvailabilityServiceShim:
    """Domain 3 — shared.availability_service must re-export availability symbols."""

    def test_shared_availability_service_importable(self):
        mod = importlib.import_module("shared.availability_service")
        assert mod is not None

    def test_shared_availability_service_exposes_get_available_slots(self):
        mod = importlib.import_module("shared.availability_service")
        assert hasattr(mod, "get_available_slots"), "get_available_slots missing from shared.availability_service"

    def test_shared_availability_service_exposes_is_holiday(self):
        mod = importlib.import_module("shared.availability_service")
        assert hasattr(mod, "is_holiday"), "is_holiday missing from shared.availability_service"

    def test_shared_availability_service_exposes_get_calendar_events_for_range(self):
        mod = importlib.import_module("shared.availability_service")
        assert hasattr(
            mod, "get_calendar_events_for_range"
        ), "get_calendar_events_for_range missing from shared.availability_service"

    def test_shared_availability_service_has_all(self):
        mod = importlib.import_module("shared.availability_service")
        assert hasattr(mod, "__all__"), "shared.availability_service must define __all__"
        required = {"get_available_slots", "is_holiday", "get_calendar_events_for_range"}
        assert required.issubset(set(mod.__all__)), f"__all__ missing: {required - set(mod.__all__)}"

    def test_shared_availability_service_symbols_are_same_objects_as_agent(self):
        """Forward shim must delegate to agent implementation objects.

        The shim re-exports by reference (`from agent... import X`), so identity
        already holds on a normal import. Do NOT del+reimport sys.modules here —
        that recreates module objects (and module-level caches) and pollutes later
        tests in full-suite order.
        """
        shim = importlib.import_module("shared.availability_service")
        canonical = importlib.import_module("agent.services.availability_service")
        assert shim.get_available_slots is canonical.get_available_slots
        assert shim.is_holiday is canonical.is_holiday
        assert shim.get_calendar_events_for_range is canonical.get_calendar_events_for_range


# ---------------------------------------------------------------------------
# shared/gcal_push_service.py shim
# ---------------------------------------------------------------------------


class TestGcalPushServiceShim:
    """Domain 3 — shared.gcal_push_service must re-export push symbols."""

    def test_shared_gcal_push_service_importable(self):
        mod = importlib.import_module("shared.gcal_push_service")
        assert mod is not None

    def test_shared_gcal_push_service_exposes_delete_gcal_event(self):
        mod = importlib.import_module("shared.gcal_push_service")
        assert hasattr(mod, "delete_gcal_event"), "delete_gcal_event missing"

    def test_shared_gcal_push_service_exposes_push_appointment_to_gcal(self):
        mod = importlib.import_module("shared.gcal_push_service")
        assert hasattr(mod, "push_appointment_to_gcal"), "push_appointment_to_gcal missing"

    def test_shared_gcal_push_service_exposes_update_appointment_in_gcal(self):
        mod = importlib.import_module("shared.gcal_push_service")
        assert hasattr(mod, "update_appointment_in_gcal"), "update_appointment_in_gcal missing"

    def test_shared_gcal_push_service_exposes_fire_and_forget_push_blocking_event(self):
        mod = importlib.import_module("shared.gcal_push_service")
        assert hasattr(
            mod, "fire_and_forget_push_blocking_event"
        ), "fire_and_forget_push_blocking_event missing"

    def test_shared_gcal_push_service_exposes_update_blocking_event_in_gcal(self):
        mod = importlib.import_module("shared.gcal_push_service")
        assert hasattr(mod, "update_blocking_event_in_gcal"), "update_blocking_event_in_gcal missing"

    def test_shared_gcal_push_service_has_all(self):
        mod = importlib.import_module("shared.gcal_push_service")
        assert hasattr(mod, "__all__"), "shared.gcal_push_service must define __all__"
        required = {
            "delete_gcal_event",
            "push_appointment_to_gcal",
            "update_appointment_in_gcal",
            "fire_and_forget_push_blocking_event",
            "update_blocking_event_in_gcal",
        }
        assert required.issubset(set(mod.__all__)), f"__all__ missing: {required - set(mod.__all__)}"


# ---------------------------------------------------------------------------
# shared/recurrence_service.py shim
# ---------------------------------------------------------------------------


class TestRecurrenceServiceShim:
    """Domain 3 — shared.recurrence_service must re-export recurrence symbols."""

    def test_shared_recurrence_service_importable(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert mod is not None

    def test_shared_recurrence_service_exposes_expand_recurrence(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert hasattr(mod, "expand_recurrence"), "expand_recurrence missing"

    def test_shared_recurrence_service_exposes_check_conflicts_for_dates(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert hasattr(mod, "check_conflicts_for_dates"), "check_conflicts_for_dates missing"

    def test_shared_recurrence_service_exposes_get_business_hours_summary(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert hasattr(mod, "get_business_hours_summary"), "get_business_hours_summary missing"

    def test_shared_recurrence_service_exposes_get_remaining_week_days(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert hasattr(mod, "get_remaining_week_days"), "get_remaining_week_days missing"

    def test_shared_recurrence_service_exposes_format_byday(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert hasattr(mod, "format_byday"), "format_byday missing"

    def test_shared_recurrence_service_exposes_format_bymonthday(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert hasattr(mod, "format_bymonthday"), "format_bymonthday missing"

    def test_shared_recurrence_service_exposes_parse_byday(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert hasattr(mod, "parse_byday"), "parse_byday missing"

    def test_shared_recurrence_service_has_all(self):
        mod = importlib.import_module("shared.recurrence_service")
        assert hasattr(mod, "__all__"), "shared.recurrence_service must define __all__"
        required = {
            "expand_recurrence",
            "check_conflicts_for_dates",
            "get_business_hours_summary",
            "get_remaining_week_days",
            "format_byday",
            "format_bymonthday",
            "parse_byday",
        }
        assert required.issubset(set(mod.__all__)), f"__all__ missing: {required - set(mod.__all__)}"


# ---------------------------------------------------------------------------
# shared/catalog_builder.py shim
# ---------------------------------------------------------------------------


class TestCatalogBuilderShim:
    """Domain 3 — shared.catalog_builder must re-export invalidate_catalog_cache."""

    def test_shared_catalog_builder_importable(self):
        mod = importlib.import_module("shared.catalog_builder")
        assert mod is not None

    def test_shared_catalog_builder_exposes_invalidate_catalog_cache(self):
        mod = importlib.import_module("shared.catalog_builder")
        assert hasattr(mod, "invalidate_catalog_cache"), "invalidate_catalog_cache missing"

    def test_shared_catalog_builder_has_all(self):
        mod = importlib.import_module("shared.catalog_builder")
        assert hasattr(mod, "__all__"), "shared.catalog_builder must define __all__"
        assert "invalidate_catalog_cache" in mod.__all__

    def test_shared_catalog_builder_symbol_is_same_object_as_agent(self):
        # Shim re-exports by reference; identity holds on a normal import. Do NOT
        # del+reimport sys.modules (it recreates the catalog_builder cache and
        # pollutes later full-suite tests).
        shim = importlib.import_module("shared.catalog_builder")
        canonical = importlib.import_module("agent.prompts.catalog_builder")
        assert shim.invalidate_catalog_cache is canonical.invalidate_catalog_cache


# ---------------------------------------------------------------------------
# shared/customer_resolve.py shim
# ---------------------------------------------------------------------------


class TestCustomerResolveShim:
    """Domain 3 — shared.customer_resolve must re-export _invalidate_cached_customer."""

    def test_shared_customer_resolve_importable(self):
        mod = importlib.import_module("shared.customer_resolve")
        assert mod is not None

    def test_shared_customer_resolve_exposes_invalidate_cached_customer(self):
        mod = importlib.import_module("shared.customer_resolve")
        assert hasattr(mod, "_invalidate_cached_customer"), "_invalidate_cached_customer missing"

    def test_shared_customer_resolve_has_all(self):
        mod = importlib.import_module("shared.customer_resolve")
        assert hasattr(mod, "__all__"), "shared.customer_resolve must define __all__"
        assert "_invalidate_cached_customer" in mod.__all__


# ---------------------------------------------------------------------------
# Domain 3 acceptance gate — zero agent imports in api/
# ---------------------------------------------------------------------------


class TestZeroAgentImportsInApi:
    """Domain 3 — api/ must contain zero direct agent imports."""

    def test_admin_py_has_zero_agent_imports(self):
        """SPEC: grep 'from agent.' api/routes/admin.py must return 0 matches."""
        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        admin_py = os.path.join(root_dir, "api", "routes", "admin.py")
        with open(admin_py) as f:
            lines = f.readlines()
        agent_imports = [
            line.strip()
            for line in lines
            if line.strip().startswith("from agent.")
        ]
        assert agent_imports == [], (
            f"admin.py still has {len(agent_imports)} agent import(s):\n"
            + "\n".join(agent_imports)
        )

    def test_admin_py_has_no_agent_imports_grep(self):
        """SPEC: grep 'from agent.' api/routes/admin.py returns 0 matches.

        Note: system.py and google_oauth.py still import agent.workers.gcal_sync_worker
        and agent.services.google_oauth_service respectively — those are out of scope
        for this task set (only admin.py cross-boundary imports were listed in tasks 3.6).
        """
        import subprocess

        tests_dir = os.path.dirname(__file__)
        root_dir = os.path.dirname(os.path.dirname(tests_dir))
        admin_py = os.path.join(root_dir, "api", "routes", "admin.py")
        result = subprocess.run(
            ["grep", "-n", "from agent.", admin_py],
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", (
            f"Found agent imports in admin.py:\n{result.stdout}"
        )
