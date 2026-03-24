"""Unit tests for the token tracking service."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.services.token_tracking import record_token_usage


@pytest.mark.asyncio
async def test_record_token_usage_skips_zero_tokens():
    """Zero tokens should be silently skipped (no DB call)."""
    with patch("agent.services.token_tracking.get_async_session") as mock_session:
        await record_token_usage(input_tokens=0, output_tokens=0)
        mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_record_token_usage_skips_negative_tokens():
    """Negative tokens should be silently skipped (no DB call)."""
    with patch("agent.services.token_tracking.get_async_session") as mock_session:
        await record_token_usage(input_tokens=-1, output_tokens=-5)
        mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_record_token_usage_calls_upsert():
    """Valid tokens should trigger a DB upsert."""
    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "agent.services.token_tracking.get_async_session", return_value=mock_ctx
    ):
        await record_token_usage(input_tokens=500, output_tokens=200)

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_record_token_usage_handles_db_error_gracefully():
    """DB errors should be caught and logged, never raised."""
    mock_session = AsyncMock()
    mock_session.execute.side_effect = Exception("DB connection lost")
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "agent.services.token_tracking.get_async_session", return_value=mock_ctx
    ):
        # Should NOT raise
        await record_token_usage(input_tokens=100, output_tokens=50)


@pytest.mark.asyncio
async def test_record_token_usage_accepts_input_only():
    """Should work with only input tokens (output = 0)."""
    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "agent.services.token_tracking.get_async_session", return_value=mock_ctx
    ):
        await record_token_usage(input_tokens=100, output_tokens=0)

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_record_token_usage_accepts_output_only():
    """Should work with only output tokens (input = 0)."""
    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "agent.services.token_tracking.get_async_session", return_value=mock_ctx
    ):
        await record_token_usage(input_tokens=0, output_tokens=300)

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
