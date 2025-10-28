"""
FastAPI API Service Entry Point
Webhook receiver for Chatwoot and Stripe events
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from api.middleware.rate_limiting import RateLimitMiddleware
from api.routes import chatwoot
from api.routes import stripe as stripe_routes
from shared.logging_config import configure_logging

# Configure structured JSON logging on startup
configure_logging()

app = FastAPI(
    title="Atrévete Bot API",
    description="Webhook receiver for WhatsApp conversations via Chatwoot and Stripe",
    version="1.0.0",
)

# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# Add CORS middleware (webhooks can come from external services)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for webhooks
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include webhook routers
app.include_router(chatwoot.router, prefix="/webhook", tags=["webhooks"])
app.include_router(stripe_routes.router, prefix="/webhook", tags=["webhooks"])


# Exception handler for validation errors
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Return 400 with validation error details."""
    return JSONResponse(
        status_code=400,
        content={"error": "Validation error", "details": exc.errors()},
    )


@app.get("/health")
async def health_check() -> JSONResponse:
    """
    Health check endpoint for Docker health checks and monitoring.

    Checks:
    - Redis connectivity (PING command)
    - PostgreSQL connectivity (SELECT 1 query)

    Returns:
        200 OK if all systems healthy
        503 Service Unavailable if degraded
    """
    from sqlalchemy import text

    from database.connection import get_async_session
    from shared.redis_client import get_redis_client

    health_status = {
        "status": "healthy",
        "redis": "unknown",
        "postgres": "unknown",
    }
    status_code = 200

    # Check Redis connectivity
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        health_status["redis"] = "connected"
    except Exception:
        health_status["redis"] = "disconnected"
        health_status["status"] = "degraded"
        status_code = 503

    # Check PostgreSQL connectivity
    try:
        async for session in get_async_session():
            await session.execute(text("SELECT 1"))
            health_status["postgres"] = "connected"
            break
    except Exception:
        health_status["postgres"] = "disconnected"
        health_status["status"] = "degraded"
        status_code = 503

    return JSONResponse(status_code=status_code, content=health_status)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint"""
    return {"message": "Atrévete Bot API - Use /health for health checks"}
