"""Rate limiting middleware using Redis."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from shared.config import get_settings
from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Rate limit: 10 requests per minute per IP (general)
RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60

# Rate limit for login endpoint (stricter - brute force protection)
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce rate limiting using Redis.

    Limits requests to 10 per minute per source IP address.
    Returns 429 Too Many Requests if limit is exceeded.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request with rate limiting.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/route handler

        Returns:
            Response with rate limit headers
            429 if rate limit exceeded
        """
        # Skip rate limiting for health check endpoint
        if request.url.path == "/health":
            return await call_next(request)

        # Extract client IP (consider X-Forwarded-For for proxied requests)
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take first IP in chain (original client)
            client_ip = forwarded_for.split(",")[0].strip()

        try:
            redis_client = get_redis_client()

            # SPECIAL CASE: Login endpoint - always apply strict rate limiting
            # This prevents brute force attacks regardless of any headers
            if request.url.path == "/api/admin/auth/login":
                return await self._rate_limit_login(
                    request, call_next, redis_client, client_ip
                )

            # For other admin routes: skip rate limiting ONLY if token is VALID
            if request.url.path.startswith("/api/admin/"):
                auth_header = request.headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header.split(" ", 1)[1]
                    if self._is_valid_token(token):
                        # Token verified - skip rate limiting for authenticated users
                        return await call_next(request)
                    # Invalid token - fall through to apply rate limiting

            # Apply standard rate limiting
            return await self._apply_rate_limit(
                request, call_next, redis_client, client_ip
            )

        except Exception as e:
            # Log error but don't block request if Redis fails
            logger.error(f"Rate limit check failed for IP {client_ip}: {e}")
            # Proceed without rate limiting if Redis is unavailable
            fallback_response: Response = await call_next(request)
            return fallback_response

    def _is_valid_token(self, token: str) -> bool:
        """
        Verify if JWT token is valid.

        Only checks signature and expiration - actual authorization
        is handled by the route dependencies.
        """
        try:
            settings = get_settings()
            secret = getattr(settings, "ADMIN_JWT_SECRET", None)
            if not secret:
                return False

            payload = jwt.decode(token, secret, algorithms=["HS256"])
            return payload.get("type") == "admin"
        except JWTError:
            return False
        except Exception:
            return False

    async def _rate_limit_login(
        self,
        request: Request,
        call_next: Callable,
        redis_client,
        client_ip: str,
    ) -> Response:
        """
        Apply strict rate limiting to login endpoint.

        Limits to 5 attempts per 5 minutes per IP to prevent brute force.
        """
        # Use 5-minute window for login attempts
        current_window = datetime.now(UTC).strftime("%Y-%m-%d:%H:") + str(
            datetime.now(UTC).minute // 5
        )
        redis_key = f"login_attempts:{client_ip}:{current_window}"

        # Increment attempt count
        attempts = await redis_client.incr(redis_key)

        # Set TTL on first attempt
        if attempts == 1:
            await redis_client.expire(redis_key, LOGIN_RATE_LIMIT_WINDOW_SECONDS)

        # Check if limit exceeded
        if attempts > LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
            logger.warning(
                f"Login rate limit exceeded for IP {client_ip}: "
                f"{attempts} attempts in {LOGIN_RATE_LIMIT_WINDOW_SECONDS}s window"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many login attempts",
                    "detail": f"Please try again in {LOGIN_RATE_LIMIT_WINDOW_SECONDS // 60} minutes",
                },
                headers={
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(LOGIN_RATE_LIMIT_WINDOW_SECONDS),
                },
            )

        # Proceed with login attempt
        remaining = max(0, LOGIN_RATE_LIMIT_MAX_ATTEMPTS - attempts)
        response: Response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    async def _apply_rate_limit(
        self,
        request: Request,
        call_next: Callable,
        redis_client,
        client_ip: str,
    ) -> Response:
        """Apply standard rate limiting (10 requests/minute)."""
        current_minute = datetime.now(UTC).strftime("%Y-%m-%d:%H:%M")
        redis_key = f"rate_limit:{client_ip}:{current_minute}"

        # Increment request count for this IP in current minute
        request_count = await redis_client.incr(redis_key)

        # Set TTL on first request (key creation)
        if request_count == 1:
            await redis_client.expire(redis_key, RATE_LIMIT_WINDOW_SECONDS)

        # Calculate remaining requests
        remaining = max(0, RATE_LIMIT_MAX_REQUESTS - request_count)

        # Check if rate limit exceeded
        if request_count > RATE_LIMIT_MAX_REQUESTS:
            logger.warning(
                f"Rate limit exceeded for IP {client_ip}: {request_count} requests"
            )
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0"},
            )

        # Proceed with request
        response: Response = await call_next(request)

        # Add rate limit header to response
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response
