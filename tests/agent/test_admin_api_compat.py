"""Compat tests — admin.py imports must resolve — Task 7.4.

These tests verify that the module symbols referenced inside lazy-import blocks
in api/routes/admin.py and api/routes/system.py are importable after Phase 7.

Phase 1 (agent-tools-shared-extraction): dead endpoint and its shim module
removed. The two availability shim tests were deleted along with the dead code.

Phase 2 (agent-tools-shared-extraction): calendar implementation moved to
shared/calendar_service.py. Tests now assert symbols come from shared.calendar_service
(canonical path) while also confirming the legacy agent.tools.calendar_tools path
still resolves via backward-compat reverse shim.
"""

import importlib


def test_calendar_tools_importable():
    """agent.tools.calendar_tools must be importable (backward-compat shim)."""
    mod = importlib.import_module("agent.tools.calendar_tools")
    assert mod is not None


def test_calendar_tools_exposes_fetch_calendar_events_async():
    """fetch_calendar_events_async must be exported from calendar_tools shim."""
    mod = importlib.import_module("agent.tools.calendar_tools")
    assert hasattr(
        mod, "fetch_calendar_events_async"
    ), "fetch_calendar_events_async not found in calendar_tools"


def test_calendar_tools_exposes_get_calendar_client():
    """get_calendar_client must be exported from calendar_tools shim."""
    mod = importlib.import_module("agent.tools.calendar_tools")
    assert hasattr(mod, "get_calendar_client"), "get_calendar_client not found in calendar_tools"


def test_shared_calendar_service_is_canonical():
    """shared.calendar_service must be importable and expose required symbols."""
    mod = importlib.import_module("shared.calendar_service")
    assert hasattr(mod, "CalendarTools"), "CalendarTools not found in shared.calendar_service"
    assert hasattr(
        mod, "get_calendar_client"
    ), "get_calendar_client not found in shared.calendar_service"
    assert hasattr(
        mod, "fetch_calendar_events_async"
    ), "fetch_calendar_events_async not found in shared.calendar_service"


def test_calendar_tools_symbols_delegate_to_shared():
    """Symbols from agent.tools.calendar_tools must be the same objects as shared.calendar_service."""
    import sys

    for mod_name in list(sys.modules.keys()):
        if mod_name in ("agent.tools.calendar_tools", "shared.calendar_service"):
            del sys.modules[mod_name]

    shim = importlib.import_module("agent.tools.calendar_tools")
    canonical = importlib.import_module("shared.calendar_service")
    assert shim.CalendarTools is canonical.CalendarTools, (
        "CalendarTools via shim is not the same object as shared.calendar_service.CalendarTools"
    )
    assert shim.get_calendar_client is canonical.get_calendar_client
    assert shim.fetch_calendar_events_async is canonical.fetch_calendar_events_async


def test_gcal_sync_worker_exposes_run_gcal_sync():
    """run_gcal_sync must be exported from agent.workers.gcal_sync_worker."""
    mod = importlib.import_module("agent.workers.gcal_sync_worker")
    assert hasattr(mod, "run_gcal_sync"), "run_gcal_sync not found in gcal_sync_worker"


def test_catalog_builder_exposes_invalidate_catalog_cache():
    """invalidate_catalog_cache must be exported from agent.prompts.catalog_builder."""
    mod = importlib.import_module("agent.prompts.catalog_builder")
    assert hasattr(
        mod, "invalidate_catalog_cache"
    ), "invalidate_catalog_cache not found in catalog_builder"
