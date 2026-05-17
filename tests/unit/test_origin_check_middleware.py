"""
Tests for OriginCheckMiddleware (admin-auth-cookie-only change, PR-1).

Covers:
- POST with allowed Origin → passes to route
- POST with disallowed Origin → 403
- POST with no Origin (server-to-server) on exempt path → passes
- GET with any Origin → passes (only mutating verbs are blocked)
- Webhook exempt paths bypass origin check
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(method: str, path: str, origin: str | None = None) -> MagicMock:
    """Build a minimal Starlette-like Request mock."""
    request = MagicMock()
    request.method = method
    request.url.path = path

    headers: dict[str, str] = {}
    if origin is not None:
        headers["origin"] = origin
    request.headers = headers

    return request


async def _call_next_ok(request):
    """Dummy call_next that returns a 200 response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    return mock_response


# ---------------------------------------------------------------------------
# T7-1: POST with allowed Origin → passes through
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_allowed_origin_passes():
    """POST from an allowed origin must reach the route handler."""
    from api.middleware.origin_check import OriginCheckMiddleware

    middleware = OriginCheckMiddleware(app=MagicMock())
    request = _make_request("POST", "/api/admin/customers", origin="https://admin.example.com")

    with patch("api.middleware.origin_check.get_settings") as mock_settings:
        mock_settings.return_value.CORS_ORIGINS = "https://admin.example.com"
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# T7-2: POST with disallowed Origin → 403
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_disallowed_origin_returns_403():
    """POST from a disallowed origin must be rejected with 403."""
    from api.middleware.origin_check import OriginCheckMiddleware

    middleware = OriginCheckMiddleware(app=MagicMock())
    request = _make_request("POST", "/api/admin/customers", origin="https://evil.example.com")

    with patch("api.middleware.origin_check.get_settings") as mock_settings:
        mock_settings.return_value.CORS_ORIGINS = "https://admin.example.com"
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# T7-3: POST with no Origin on exempt path → passes (Stripe/Chatwoot webhooks)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stripe_webhook_no_origin_passes():
    """POST to Stripe webhook with no Origin must pass through (server-to-server)."""
    from api.middleware.origin_check import OriginCheckMiddleware

    middleware = OriginCheckMiddleware(app=MagicMock())
    request = _make_request("POST", "/api/billing/stripe/webhook", origin=None)

    with patch("api.middleware.origin_check.get_settings") as mock_settings:
        mock_settings.return_value.CORS_ORIGINS = "https://admin.example.com"
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_chatwoot_webhook_no_origin_passes():
    """POST to Chatwoot webhook with no Origin must pass through (server-to-server)."""
    from api.middleware.origin_check import OriginCheckMiddleware

    middleware = OriginCheckMiddleware(app=MagicMock())
    request = _make_request("POST", "/webhook/chatwoot", origin=None)

    with patch("api.middleware.origin_check.get_settings") as mock_settings:
        mock_settings.return_value.CORS_ORIGINS = "https://admin.example.com"
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# T7-4: GET with disallowed Origin → passes (only mutating verbs blocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_with_disallowed_origin_passes():
    """GET requests must not be blocked regardless of Origin."""
    from api.middleware.origin_check import OriginCheckMiddleware

    middleware = OriginCheckMiddleware(app=MagicMock())
    request = _make_request("GET", "/api/admin/customers", origin="https://evil.example.com")

    with patch("api.middleware.origin_check.get_settings") as mock_settings:
        mock_settings.return_value.CORS_ORIGINS = "https://admin.example.com"
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# T7-5: PUT and DELETE also blocked by disallowed Origin
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_disallowed_origin_returns_403():
    """PUT from a disallowed origin must also return 403."""
    from api.middleware.origin_check import OriginCheckMiddleware

    middleware = OriginCheckMiddleware(app=MagicMock())
    request = _make_request("PUT", "/api/admin/customers/123", origin="https://evil.example.com")

    with patch("api.middleware.origin_check.get_settings") as mock_settings:
        mock_settings.return_value.CORS_ORIGINS = "https://admin.example.com"
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_disallowed_origin_returns_403():
    """DELETE from a disallowed origin must return 403."""
    from api.middleware.origin_check import OriginCheckMiddleware

    middleware = OriginCheckMiddleware(app=MagicMock())
    request = _make_request("DELETE", "/api/admin/customers/123", origin="https://evil.example.com")

    with patch("api.middleware.origin_check.get_settings") as mock_settings:
        mock_settings.return_value.CORS_ORIGINS = "https://admin.example.com"
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# T7-6: POST with no Origin on a non-exempt admin path → 403 (not server-to-server)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_no_origin_non_exempt_path_returns_403():
    """POST with no Origin on a non-exempt admin path must return 403.

    Rationale: no-origin on browser-targeted admin routes suggests a cross-origin
    fetch without Origin header — treated as suspicious and blocked.
    """
    from api.middleware.origin_check import OriginCheckMiddleware

    middleware = OriginCheckMiddleware(app=MagicMock())
    # Note: no origin header on a regular admin route (not a webhook)
    request = _make_request("POST", "/api/admin/customers", origin=None)

    with patch("api.middleware.origin_check.get_settings") as mock_settings:
        mock_settings.return_value.CORS_ORIGINS = "https://admin.example.com"
        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 403
