"""Rate limiting middleware using Redis."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Rate limit: 10 requests per minute per IP
RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60


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
        # Skip rate limiting for authenticated admin routes
        # Admin panel already requires JWT authentication, no need to rate limit
        if request.url.path.startswith("/api/admin/"):
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                # Has valid authorization header format, skip rate limiting
                return await call_next(request)

        # Skip rate limiting for health check endpoint
        if request.url.path == "/health":
            return await call_next(request)

        # Extract client IP
        client_ip = request.client.host if request.client else "unknown"

        # Create Redis key with current minute
        current_minute = datetime.now(UTC).strftime("%Y-%m-%d:%H:%M")
        redis_key = f"rate_limit:{client_ip}:{current_minute}"

        try:
            redis_client = get_redis_client()

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

        except Exception as e:
            # Log error but don't block request if Redis fails
            logger.error(f"Rate limit check failed for IP {client_ip}: {e}")
            # Proceed without rate limiting if Redis is unavailable
            fallback_response: Response = await call_next(request)
            return fallback_response
