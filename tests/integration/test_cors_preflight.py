"""CORS preflight regression tests.

Regression for the escalation-resolve 503 found in live UAT (2026-06-16): the admin panel's
PATCH requests (escalation resolve, note edit, user edit, calendar config, billing) were
blocked because "PATCH" was missing from CORSMiddleware allow_methods. The browser's OPTIONS
preflight returned 400 and the actual PATCH was never sent, surfacing to the user as a failed
mutation. These tests assert every HTTP method the admin panel uses survives CORS preflight.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app

# Present in the default CORS_ORIGINS allow-list (shared/config.py).
ALLOWED_ORIGIN = "http://localhost:3000"

# One representative route per mutating method the admin panel issues.
PATCH_ROUTE = "/api/admin/escalations/00000000-0000-0000-0000-000000000000/resolve"


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("method", ["PATCH", "POST", "PUT", "DELETE", "GET"])
def test_preflight_allows_mutating_methods(client, method):
    """An OPTIONS preflight from an allowed origin must succeed for every method the UI uses.

    Before the fix, method="PATCH" returned 400 (PATCH absent from allow_methods).
    """
    resp = client.options(
        PATCH_ROUTE,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": method,
        },
    )
    assert resp.status_code == 200, (
        f"CORS preflight for {method} must return 200, got {resp.status_code}"
    )
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert method in allow_methods, (
        f"Access-Control-Allow-Methods must include {method}, got: {allow_methods!r}"
    )
