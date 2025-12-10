"""
Startup configuration validation module.

This module provides startup-time validation for critical configuration
to catch misconfigurations early (fail-fast) rather than at runtime when
a customer tries to use the feature.

Usage:
    from shared.startup_validator import validate_startup_config, StartupValidationError

    async def main():
        try:
            await validate_startup_config()
        except StartupValidationError as e:
            logger.critical(f"Startup blocked: {e}")
            sys.exit(1)
"""

import logging
from pathlib import Path

from shared.config import get_settings

logger = logging.getLogger(__name__)


class StartupValidationError(Exception):
    """Raised when critical startup validation fails."""

    pass


async def validate_startup_config(require_google_calendar: bool = True) -> dict[str, bool]:
    """
    Validate all critical configuration at startup.

    Performs tiered validation:
    - TIER 1 (CRITICAL): Block startup if any fail
    - TIER 2 (IMPORTANT): Warn but allow startup

    Args:
        require_google_calendar: If True, Google Calendar credentials are CRITICAL.
                                 If False, they're IMPORTANT (warn but continue).
                                 Set to False for services that don't use Calendar (e.g., API).

    Returns:
        dict of {check_name: passed} for all validations

    Raises:
        StartupValidationError: If any CRITICAL check fails
    """
    settings = get_settings()
    results: dict[str, bool] = {}
    critical_failures: list[str] = []

    # =========================================================================
    # TIER 1: CRITICAL (block startup if any fail)
    # =========================================================================

    # 1. Google Calendar credentials file exists and readable
    gc_path = Path(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    gc_error = None

    if settings.GOOGLE_SERVICE_ACCOUNT_JSON == "/path/to/service-account-key.json":
        gc_error = (
            "GOOGLE_SERVICE_ACCOUNT_JSON is default placeholder - "
            "set path to your service account key file"
        )
        results["google_calendar_file"] = False
    elif not gc_path.exists():
        gc_error = f"Google Calendar credentials file not found: {gc_path}"
        results["google_calendar_file"] = False
    elif not gc_path.is_file():
        gc_error = f"Google Calendar credentials path is not a file: {gc_path}"
        results["google_calendar_file"] = False
    else:
        # File exists - check if it's readable and non-empty
        try:
            content = gc_path.read_text()
            if len(content) < 100:  # Valid JSON key file is typically >1KB
                gc_error = (
                    f"Google Calendar credentials file appears empty or invalid: {gc_path}"
                )
                results["google_calendar_file"] = False
            else:
                results["google_calendar_file"] = True
                logger.info(f"  [OK] Google Calendar credentials: {gc_path}")
        except PermissionError:
            gc_error = (
                f"Google Calendar credentials file not readable (permission denied): {gc_path}"
            )
            results["google_calendar_file"] = False

    # Add to critical_failures only if require_google_calendar=True
    if gc_error:
        if require_google_calendar:
            critical_failures.append(gc_error)
        else:
            logger.warning(f"  [WARN] {gc_error} (not required for this service)")

    # 2. OpenRouter API key format validation
    if settings.OPENROUTER_API_KEY == "sk-or-placeholder":
        critical_failures.append(
            "OPENROUTER_API_KEY is placeholder - set your OpenRouter API key"
        )
        results["openrouter_api_key"] = False
    elif not settings.OPENROUTER_API_KEY.startswith("sk-or-"):
        # OpenRouter keys typically start with sk-or-v1- but we check prefix only
        logger.warning(
            "OPENROUTER_API_KEY doesn't start with 'sk-or-' - verify it's correct"
        )
        results["openrouter_api_key"] = True  # Allow but warn
    else:
        results["openrouter_api_key"] = True
        logger.info("  [OK] OpenRouter API key configured")

    # 3. Chatwoot API token validation
    if settings.CHATWOOT_API_TOKEN == "placeholder":
        critical_failures.append(
            "CHATWOOT_API_TOKEN is placeholder - set your Chatwoot API token"
        )
        results["chatwoot_token"] = False
    else:
        results["chatwoot_token"] = True
        logger.info("  [OK] Chatwoot API token configured")

    # 4. Redis Stack modules check (requires connection)
    try:
        from shared.redis_client import get_redis_client

        redis = get_redis_client()
        # Check for Redis Stack modules (search, ReJSON)
        # Note: get_redis_client returns async Redis client, must await
        modules = await redis.execute_command("MODULE", "LIST")
        module_names = []
        for m in modules:
            if len(m) >= 2:
                name = m[1].decode() if isinstance(m[1], bytes) else m[1]
                module_names.append(name.lower())

        has_search = "search" in module_names or "ft" in module_names
        has_json = "rejson" in module_names or "json" in module_names

        if not has_search:
            critical_failures.append(
                "Redis Stack module 'search' (RedisSearch) not available - "
                "use redis/redis-stack image instead of redis:alpine"
            )
            results["redis_search_module"] = False
        else:
            results["redis_search_module"] = True
            logger.info("  [OK] Redis Search module available")

        if not has_json:
            critical_failures.append(
                "Redis Stack module 'ReJSON' not available - "
                "use redis/redis-stack image instead of redis:alpine"
            )
            results["redis_json_module"] = False
        else:
            results["redis_json_module"] = True
            logger.info("  [OK] Redis JSON module available")

    except Exception as e:
        critical_failures.append(f"Redis connection failed: {e}")
        results["redis_search_module"] = False
        results["redis_json_module"] = False

    # =========================================================================
    # TIER 2: IMPORTANT (warn but allow startup)
    # =========================================================================

    # 5. Chatwoot webhook token minimum length (security)
    if len(settings.CHATWOOT_WEBHOOK_TOKEN) < 24:
        logger.warning(
            "CHATWOOT_WEBHOOK_TOKEN should be at least 24 characters for security"
        )
        results["webhook_token_length"] = False
    else:
        results["webhook_token_length"] = True

    # 6. Database URL format validation
    if not settings.DATABASE_URL.startswith("postgresql+asyncpg://"):
        logger.warning(
            "DATABASE_URL should use asyncpg driver: postgresql+asyncpg://..."
        )
        results["database_url_format"] = False
    else:
        results["database_url_format"] = True

    # 7. Langfuse configuration (optional but recommended)
    if settings.LANGFUSE_PUBLIC_KEY == "pk-lf-placeholder":
        logger.info(
            "  [INFO] Langfuse not configured - observability disabled"
        )
        results["langfuse_configured"] = False
    else:
        results["langfuse_configured"] = True
        logger.info("  [OK] Langfuse configured for observability")

    # 8. Groq API key for audio (optional)
    if settings.GROQ_API_KEY == "gsk-placeholder":
        logger.info(
            "  [INFO] Groq API not configured - audio transcription disabled"
        )
        results["groq_configured"] = False
    else:
        results["groq_configured"] = True
        logger.info("  [OK] Groq API configured for audio transcription")

    # =========================================================================
    # Summary and result
    # =========================================================================

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    logger.info(f"Startup validation: {passed}/{total} checks passed")

    if critical_failures:
        logger.critical("=" * 60)
        logger.critical("STARTUP BLOCKED - Critical configuration errors:")
        for i, failure in enumerate(critical_failures, 1):
            logger.critical(f"  {i}. {failure}")
        logger.critical("=" * 60)
        raise StartupValidationError(
            f"Critical startup validation failed ({len(critical_failures)} errors): "
            f"{'; '.join(critical_failures)}"
        )

    return results


async def validate_database_connection() -> bool:
    """
    Validate database connection is working.

    This is a separate check because it's slower and may be called
    after basic config validation.

    Returns:
        True if database connection successful, False otherwise
    """
    try:
        from database.connection import get_async_session

        async for session in get_async_session():
            # Simple query to verify connection
            result = await session.execute("SELECT 1")
            result.scalar()
            break

        logger.info("  [OK] Database connection successful")
        return True

    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
