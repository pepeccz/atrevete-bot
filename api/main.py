"""
FastAPI API Service Entry Point
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from api.middleware.rate_limiting import RateLimitMiddleware
from api.routes import admin, chatwoot, conversations
from shared.config import get_settings
from shared.logging_config import configure_logging
from shared.startup_validator import StartupValidationError, validate_startup_config

# Configure structured JSON logging on startup
configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Atrévete Bot API",
    version="1.0.0",
)

# Load settings for CORS configuration
settings = get_settings()
origins = settings.CORS_ORIGINS.split(",")

# Add rate limiting middleware FIRST (executes LAST, closest to routes)
app.add_middleware(RateLimitMiddleware)

# Add CORS middleware LAST (executes FIRST, handles preflight OPTIONS before rate limiting)
# In FastAPI/Starlette, last added middleware executes first
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Include webhook routers
app.include_router(chatwoot.router, prefix="/webhook", tags=["webhooks"])

# Include conversation history router
app.include_router(conversations.router, tags=["conversations"])

# Include admin panel router
app.include_router(admin.router, tags=["admin"])


# =========================================================================
# STARTUP VALIDATION (Fase 4 - Config Validation)
# =========================================================================
@app.on_event("startup")
async def startup_config_validation():
    """
    Validate critical configuration at startup.

    This catches misconfigurations early (fail-fast) rather than at runtime
    when a customer tries to use the feature.

    Note: API doesn't require Google Calendar credentials (only agent uses it).

    Raises:
        StartupValidationError: If critical configuration is invalid
    """
    logger.info("Running API startup configuration validation...")
    try:
        # API doesn't use Google Calendar directly - only agent does
        await validate_startup_config(require_google_calendar=False)
        logger.info("API startup configuration validation passed")
    except StartupValidationError as e:
        logger.critical(f"API startup blocked due to configuration errors: {e}")
        raise  # FastAPI will fail to start


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
        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
            health_status["postgres"] = "connected"
    except Exception:
        health_status["postgres"] = "disconnected"
        health_status["status"] = "degraded"
        status_code = 503

    return JSONResponse(status_code=status_code, content=health_status)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint"""
    return {"message": "Atrévete Bot API by zanovix.com - Use /health for health checks"}
