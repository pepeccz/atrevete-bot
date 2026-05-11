"""
Parametrized regression snapshot: every route that requires authentication
returns 401 when no cookie token is present.

Strategy:
- Import the FastAPI `app` from api.main (conftest.py stubs pydub/audioop).
- Walk app.routes filtering for APIRoute instances.
- For each route, traverse the dependency graph to check whether
  `get_current_user` appears — these are the authenticated routes.
- Assert:
  1. The authenticated route count is ≥ 80 (T2.11 counter assertion).
  2. Each authenticated route returns 401 when hit WITHOUT a cookie.

This test DOES NOT require a live database or Redis — the auth short-circuit
in get_current_user raises 401 before any DB lookup is attempted when the
cookie is absent.

Traces: SC-PERM-4, T2.5, T2.11 (design §6.4).
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flatten_dependencies(dependant):
    """Yield all DependencyModel nodes recursively from a FastAPI Dependant."""
    yield dependant
    for sub in dependant.dependencies:
        yield from _flatten_dependencies(sub)


def _collect_authenticated_routes(app) -> list[tuple[str, str]]:
    """
    Return a list of (method, path) tuples for all routes whose dependency
    graph includes get_current_user.

    We detect auth dependency by inspecting the flattened dependant.call chain.
    """
    # Import here (inside test) so conftest.py pydub stub is already applied
    from api.dependencies.auth import get_current_user

    authenticated: list[tuple[str, str]] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = {dep.call for dep in _flatten_dependencies(route.dependant)}
        if get_current_user not in calls:
            continue
        for method in route.methods or ["GET"]:
            authenticated.append((method, route.path))

    return authenticated


# ---------------------------------------------------------------------------
# Module-level fixture: collect routes once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app_and_routes():
    """Load the app and pre-compute authenticated routes once per module."""
    from api.main import app

    routes = _collect_authenticated_routes(app)
    return app, routes


@pytest.fixture(scope="module")
def test_client(app_and_routes):
    """Synchronous TestClient with startup validator bypassed."""
    from unittest.mock import AsyncMock, patch

    app, _ = app_and_routes
    # Bypass startup validator — it raises StartupValidationError without real creds.
    with (
        patch(
            "api.main.validate_startup_config",
            new_callable=AsyncMock,
            return_value=None,
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        yield client


# ---------------------------------------------------------------------------
# Counter assertion (must run BEFORE the parametrized sweep)
# ---------------------------------------------------------------------------


def test_authenticated_route_count_is_at_least_80(app_and_routes):
    """
    The app MUST have at least 80 authenticated routes.

    If this count is lower, either the route discovery logic is wrong or a
    sweep commit accidentally removed auth dependencies.

    Counter assertion from T2.11 spec.
    """
    _, routes = app_and_routes
    count = len(routes)
    assert count >= 80, (
        f"Expected ≥ 80 authenticated routes, found {count}. "
        "Either route discovery is broken or auth dependencies were removed."
    )


# ---------------------------------------------------------------------------
# Parametrized 401-without-token sweep
# ---------------------------------------------------------------------------


def _route_id(method_path: tuple[str, str]) -> str:
    method, path = method_path
    return f"{method} {path}"


def test_authenticated_routes_return_401_without_token(app_and_routes):
    """
    Every authenticated route must return 401 when no token cookie is present.

    Uses a single sweep rather than per-route test functions to cover all
    authenticated routes in one shot.

    Traces: SC-PERM-4.
    """
    import re
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    app, routes = app_and_routes

    def _fill_path(path: str) -> str:
        """Replace {param} placeholders with dummy values for URL construction."""
        filled = re.sub(r"\{[^}]+_id\}", str(uuid4()), path)
        filled = re.sub(r"\{[^}]+\}", "test-value", filled)
        return filled

    failures: list[str] = []

    # Use an allowed origin so the OriginCheckMiddleware passes the request
    # through to the auth layer. Without this header, mutating requests
    # (POST/PUT/DELETE) return 403 from the middleware before auth runs.
    _origin_headers = {"Origin": "http://localhost:3000"}

    with (
        patch(
            "api.main.validate_startup_config",
            new_callable=AsyncMock,
            return_value=None,
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        for method, path in routes:
            url = _fill_path(path)
            response = client.request(method, url, cookies={}, headers=_origin_headers)
            if response.status_code != 401:
                failures.append(f"{method} {path} → {response.status_code} (expected 401)")

    assert (
        not failures
    ), f"{len(failures)} route(s) did NOT return 401 without a token:\n" + "\n".join(failures)
