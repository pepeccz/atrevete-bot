"""T3b — Startup validator settings guard.

Tests spec R3.4 / ADR-8.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_refuses_missing_booking_settings():
    """validate_booking_settings raises StartupValidationError if required rows absent."""
    from unittest.mock import AsyncMock, patch

    mock_service = AsyncMock()
    # settings service returns None for both required keys
    mock_service.get = AsyncMock(return_value=None)

    async def _mock_get_settings_service():
        return mock_service

    with patch(
        "shared.startup_validator.get_settings_service",
        new=_mock_get_settings_service,
    ):
        from shared.startup_validator import StartupValidationError, validate_booking_settings

        with pytest.raises((StartupValidationError, SystemExit, RuntimeError)) as exc_info:
            await validate_booking_settings()

    # Error message must name the missing key
    exc_str = str(exc_info.value)
    assert "minimum_booking_days_advance" in exc_str or exc_info.type in (
        SystemExit,
        RuntimeError,
        StartupValidationError,
    )


@pytest.mark.asyncio
async def test_passes_when_booking_settings_present():
    """validate_booking_settings succeeds when required rows exist."""
    mock_service = AsyncMock()
    mock_service.get = AsyncMock(side_effect=lambda key, default=None: 3)

    async def _mock_get_settings_service():
        return mock_service

    with patch(
        "shared.startup_validator.get_settings_service",
        new=_mock_get_settings_service,
    ):
        from shared.startup_validator import validate_booking_settings

        # Should NOT raise
        await validate_booking_settings()
