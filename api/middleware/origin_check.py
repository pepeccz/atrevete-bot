"""
Origin-check middleware for admin mutation routes.

Inspects the Origin header on every POST, PUT, PATCH, and DELETE request.
Requests whose Origin is not in settings.CORS_ORIGINS are rejected with 403.
Requests with no Origin header (server-to-server) are allowed through only on
explicitly exempt paths (Chatwoot webhook, Stripe webhook); all other
browserless POSTs without Origin are blocked.

CSRF defense rationale:
  SameSite=Lax + Origin allowlist. Stateless and reuses CORS_ORIGINS as the
  single source of truth — no extra tokens or non-HttpOnly cookies needed.
"""

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shared.config import get_settings


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Block mutating requests from disallowed origins."""

    MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

    # Paths that carry their own auth mechanism (HMAC signature) and must
    # not require an Origin header (they are server-to-server calls).
    EXEMPT_PATHS = (
        "/webhook/",  # Chatwoot webhook (HMAC-signed)
        "/api/billing/stripe/webhook",  # Stripe webhook (signature-verified)
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in self.MUTATING:
            return await call_next(request)

        # Exempt server-to-server webhook paths from origin check
        if any(request.url.path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        origin = request.headers.get("origin") or request.headers.get("referer", "")
        settings = get_settings()
        allowed = [o.strip() for o in settings.CORS_ORIGINS.split(",")]

        if not origin or not any(origin.startswith(a) for a in allowed):
            return JSONResponse(
                {"detail": "Origin not allowed"},
                status_code=403,
            )

        return await call_next(request)
