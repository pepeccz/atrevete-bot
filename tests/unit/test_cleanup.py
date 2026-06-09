"""Unit tests for cleanup.py safety guards (AS7, E1).

Covers:
- Empty TEST_PHONE_PREFIX raises RuntimeError before any DB query
- Prefix not starting with +349 raises RuntimeError before any DB query
- TEST_MODE_GCAL_SKIP=False raises RuntimeError (operator forgot sandbox env)
- --dry-run flag prints counts without executing deletes
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# AS7 — Safety guards
# ---------------------------------------------------------------------------


def test_cleanup_raises_on_empty_prefix() -> None:
    """AS7: cleanup raises RuntimeError when TEST_PHONE_PREFIX is empty."""
    with patch("tests.e2e.harness.cleanup.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            TEST_PHONE_PREFIX="",
            TEST_MODE_GCAL_SKIP=True,
        )

        from tests.e2e.harness.cleanup import run_cleanup

        with pytest.raises(RuntimeError, match="TEST_PHONE_PREFIX"):
            import asyncio

            asyncio.run(run_cleanup(dry_run=False, age_hours=None))


def test_cleanup_raises_on_prefix_not_starting_with_349() -> None:
    """AS7: cleanup raises RuntimeError when prefix doesn't start with +349."""
    with patch("tests.e2e.harness.cleanup.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            TEST_PHONE_PREFIX="+34600",  # Real Spanish mobile prefix — must be rejected
            TEST_MODE_GCAL_SKIP=True,
        )

        from tests.e2e.harness.cleanup import run_cleanup

        with pytest.raises(RuntimeError, match="\\+349"):
            import asyncio

            asyncio.run(run_cleanup(dry_run=False, age_hours=None))


def test_cleanup_raises_when_gcal_skip_is_false() -> None:
    """AS7: cleanup raises RuntimeError when TEST_MODE_GCAL_SKIP is False.

    Operator forgot to set sandbox env — refuse to delete real-looking data.
    """
    with patch("tests.e2e.harness.cleanup.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            TEST_PHONE_PREFIX="+34999",
            TEST_MODE_GCAL_SKIP=False,
        )

        from tests.e2e.harness.cleanup import run_cleanup

        with pytest.raises(RuntimeError, match="TEST_MODE_GCAL_SKIP"):
            import asyncio

            asyncio.run(run_cleanup(dry_run=False, age_hours=None))


@pytest.mark.asyncio
async def test_cleanup_dry_run_does_not_delete() -> None:
    """AS7/E1: dry-run mode prints counts but does not call StateResetHarness.cleanup_db."""
    with (
        patch("tests.e2e.harness.cleanup.get_settings") as mock_settings,
        patch("tests.e2e.harness.cleanup.StateResetHarness") as MockHarness,
        patch("tests.e2e.harness.cleanup._list_test_phones") as mock_list,
    ):
        mock_settings.return_value = MagicMock(
            TEST_PHONE_PREFIX="+34999",
            TEST_MODE_GCAL_SKIP=True,
        )
        mock_list.return_value = ["+34999000001", "+34999000002"]

        harness_instance = AsyncMock()
        harness_instance.cleanup_db = AsyncMock(return_value={"appointments_deleted": 0, "customer_deleted": False})
        MockHarness.return_value = harness_instance

        from tests.e2e.harness.cleanup import run_cleanup

        result = await run_cleanup(dry_run=True, age_hours=None)

    # In dry-run mode, cleanup_db must NOT be called
    harness_instance.cleanup_db.assert_not_called()
    # dry-run result should contain counts
    assert "dry_run" in result
    assert result["dry_run"] is True
    assert "phones_found" in result
    assert result["phones_found"] == 2


@pytest.mark.asyncio
async def test_cleanup_valid_config_calls_cleanup_db() -> None:
    """E1: Valid config with +34999 prefix proceeds and calls cleanup_db."""
    with (
        patch("tests.e2e.harness.cleanup.get_settings") as mock_settings,
        patch("tests.e2e.harness.cleanup.StateResetHarness") as MockHarness,
        patch("tests.e2e.harness.cleanup._list_test_phones") as mock_list,
        patch("redis.asyncio.from_url") as mock_redis,
    ):
        mock_settings.return_value = MagicMock(
            TEST_PHONE_PREFIX="+34999",
            TEST_MODE_GCAL_SKIP=True,
            REDIS_URL="redis://localhost:6379",
            REDIS_PASSWORD="",
        )
        mock_list.return_value = ["+34999000001"]

        harness_instance = AsyncMock()
        harness_instance.cleanup_db = AsyncMock(return_value={"appointments_deleted": 2, "customer_deleted": True})
        harness_instance.reset_conversation_checkpoints = AsyncMock(return_value=0)
        MockHarness.return_value = harness_instance

        mock_redis_client = AsyncMock()
        mock_redis_client.aclose = AsyncMock()
        mock_redis.return_value = mock_redis_client


        from tests.e2e.harness.cleanup import run_cleanup

        result = await run_cleanup(dry_run=False, age_hours=None)

    harness_instance.cleanup_db.assert_called_once_with("+34999000001")
    assert result["dry_run"] is False
