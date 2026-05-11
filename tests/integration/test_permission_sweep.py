"""
Regression guard: every authenticated route MUST have a require_permission
dependency OR appear in an explicit allowlist.

This test makes it IMPOSSIBLE to land a new un-gated route without either
adding require_permission or explicitly registering it in SHARED_ROUTE_ALLOWLIST.

Traces: T2.12 sweep completion, PR-3a.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

# ---------------------------------------------------------------------------
# Allowlist: routes that require authentication but do NOT need a
# require_permission gate beyond basic auth (shared across all roles).
# ---------------------------------------------------------------------------

SHARED_ROUTE_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Auth flow — only needs to be authenticated
        "GET /api/admin/auth/me",
        "POST /api/admin/auth/logout",
        # Dashboard — all authenticated users can view KPIs
        "GET /api/admin/dashboard/kpis",
        "GET /api/admin/dashboard/today-agenda",
        "GET /api/admin/dashboard/charts/appointments-trend",
        "GET /api/admin/dashboard/charts/top-services",
        "GET /api/admin/dashboard/charts/hours-worked",
        "GET /api/admin/dashboard/charts/customer-growth",
        "GET /api/admin/dashboard/charts/stylist-performance",
        # Notifications — personal per-user, no role gate needed
        "GET /api/admin/notifications",
        "GET /api/admin/notifications/paginated",
        "GET /api/admin/notifications/stats",
        "GET /api/admin/notifications/export",
        "PUT /api/admin/notifications/{notification_id}/read",
        "PUT /api/admin/notifications/mark-all-read",
        "PUT /api/admin/notifications/{notification_id}/star",
        "PUT /api/admin/notifications/{notification_id}/unread",
        "DELETE /api/admin/notifications/bulk",
        "DELETE /api/admin/notifications/{notification_id}",
        # Global search — any authenticated user can search
        "GET /api/admin/search",
        # Availability search — all authenticated users need this
        "POST /api/admin/availability/search",
    }
)


def _flatten_dependencies(dependant):
    """Yield all DependencyModel nodes recursively from a FastAPI Dependant."""
    yield dependant
    for sub in dependant.dependencies:
        yield from _flatten_dependencies(sub)


def _collect_routes_without_permission_gate(app) -> list[str]:
    """
    Return list of "METHOD /path" strings for all authenticated routes that
    lack a require_permission dependency AND are not in SHARED_ROUTE_ALLOWLIST.
    """
    from api.dependencies.auth import get_current_user

    # require_permission returns a closure — we need to detect it by looking at
    # dependency call names, since the closure name is 'require_permission_<action>'
    ungated: list[str] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        dep_calls = {dep.call for dep in _flatten_dependencies(route.dependant)}

        # Is this route authenticated?
        if get_current_user not in dep_calls:
            continue

        # Does it have a require_permission gate?
        has_permission_gate = any(
            getattr(dep.call, "__name__", "").startswith("require_permission_")
            for dep in _flatten_dependencies(route.dependant)
        )
        if has_permission_gate:
            continue

        for method in route.methods or ["GET"]:
            route_key = f"{method} {route.path}"
            if route_key not in SHARED_ROUTE_ALLOWLIST:
                ungated.append(route_key)

    return sorted(ungated)


@pytest.fixture(scope="module")
def app_fixture():
    """Load the FastAPI app once per module."""
    from api.main import app

    return app


def test_all_authenticated_routes_have_permission_gate_or_allowlist(app_fixture):
    """
    Every authenticated route must EITHER have a require_permission dependency
    OR be explicitly listed in SHARED_ROUTE_ALLOWLIST.

    This test FAILS when a new route is added without a permission gate,
    forcing the author to make an intentional allowlist decision.
    """
    ungated = _collect_routes_without_permission_gate(app_fixture)
    assert not ungated, (
        f"{len(ungated)} authenticated route(s) lack require_permission AND are not in allowlist:\n"
        + "\n".join(f"  {r}" for r in ungated)
        + "\n\nFix: add require_permission('action') to each route OR add to SHARED_ROUTE_ALLOWLIST."
    )


def test_stylist_gets_403_on_system_settings_endpoint():
    """
    Verifies that the require_permission('system:settings') chain rejects a stylist.

    Simulates the exact FastAPI dependency chain: get_current_user returns a
    stylist-role AdminUser → require_permission checks the role → raises 403.

    This proves the gate works end-to-end without needing a live JWT.
    """
    import asyncio
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from api.dependencies.auth import require_permission

    mock_stylist = MagicMock()
    mock_stylist.username = "test_stylist"
    mock_stylist.role = "stylist"
    mock_stylist.is_active = True

    checker = require_permission("system:settings")

    async def run():
        return await checker(current_user=mock_stylist)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())

    assert (
        exc_info.value.status_code == 403
    ), f"Expected 403 for stylist on system:settings, got {exc_info.value.status_code}"
    assert "system:settings" in exc_info.value.detail


def test_stylist_403_via_require_permission_direct():
    """
    Direct unit test: require_permission('system:settings') raises 403 for stylist role.
    """
    import asyncio
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from api.dependencies.auth import require_permission

    mock_stylist = MagicMock()
    mock_stylist.role = "stylist"

    checker = require_permission("system:settings")

    async def run():
        return await checker(current_user=mock_stylist)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(run())

    assert exc_info.value.status_code == 403
    assert "system:settings" in exc_info.value.detail


def test_admin_passes_require_permission_system_settings():
    """
    Direct unit test: require_permission('system:settings') passes for admin role.
    """
    import asyncio
    from unittest.mock import MagicMock

    from api.dependencies.auth import require_permission

    mock_admin = MagicMock()
    mock_admin.role = "admin"

    checker = require_permission("system:settings")

    async def run():
        return await checker(current_user=mock_admin)

    result = asyncio.run(run())
    assert result is mock_admin
