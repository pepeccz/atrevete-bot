"""
Unit tests — OAuth2 wiring in agent/workers/gcal_sync_worker._get_calendar_service().

Verifies that:
- _get_calendar_service() opens a DB session and passes it (non-None) to
  get_google_credentials()
- The AsyncSession context manager is exited (session closed) BEFORE build() is called

asyncio_mode = "auto" (set in pyproject.toml) — no @pytest.mark.asyncio needed.
No real DB or GCal network access — all dependencies are mocked.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGCalSyncWorkerOAuthWiring:
    """Verify _get_calendar_service() in gcal_sync_worker passes a session to the factory."""

    async def test_get_calendar_service_passes_session_to_factory(self):
        """
        _get_calendar_service() must open a DB session and pass it (non-None)
        to get_google_credentials(session=...).

        Arrange:
        - mock get_async_session to yield a fake AsyncSession
        - mock get_google_credentials to return fake creds
        - mock build() to return a fake service

        Assert:
        - get_google_credentials called once with a non-None session
        """
        session_mock = AsyncMock()
        mock_creds = MagicMock(name="FakeCreds")
        mock_service = MagicMock(name="FakeCalendarService")

        @contextlib.asynccontextmanager
        async def _ctx():
            yield session_mock

        with (
            patch(
                "agent.workers.gcal_sync_worker.get_async_session",
                new=_ctx,
            ),
            patch(
                "agent.workers.gcal_sync_worker.get_google_credentials",
                new=AsyncMock(return_value=mock_creds),
            ) as mock_get_creds,
            patch(
                "agent.workers.gcal_sync_worker.build",
                return_value=mock_service,
            ),
        ):
            from agent.workers.gcal_sync_worker import _get_calendar_service

            result = await _get_calendar_service()

        mock_get_creds.assert_awaited_once()
        call_args = mock_get_creds.call_args
        passed_session = call_args.kwargs.get("session") or (
            call_args.args[0] if call_args.args else None
        )
        assert passed_session is not None, (
            "get_google_credentials() must be called with a non-None session"
        )
        assert result is mock_service

    async def test_get_calendar_service_session_closed_before_build(self):
        """
        The AsyncSession context manager must be exited (session closed) BEFORE
        build() is called.

        We track call order via a shared call_log list:
        - __aexit__ appends "session_closed"
        - build() appends "build_called"

        Assert: "session_closed" appears before "build_called" in call_log.
        """
        session_mock = AsyncMock()
        mock_creds = MagicMock(name="FakeCreds")
        call_log: list[str] = []

        @contextlib.asynccontextmanager
        async def _ordered_ctx():
            yield session_mock
            call_log.append("session_closed")

        def _fake_build(*args, **kwargs):
            call_log.append("build_called")
            return MagicMock(name="FakeService")

        with (
            patch(
                "agent.workers.gcal_sync_worker.get_async_session",
                new=_ordered_ctx,
            ),
            patch(
                "agent.workers.gcal_sync_worker.get_google_credentials",
                new=AsyncMock(return_value=mock_creds),
            ),
            patch(
                "agent.workers.gcal_sync_worker.build",
                side_effect=_fake_build,
            ),
        ):
            from agent.workers.gcal_sync_worker import _get_calendar_service

            await _get_calendar_service()

        assert "session_closed" in call_log, "Session context manager was never exited"
        assert "build_called" in call_log, "build() was never called"
        session_idx = call_log.index("session_closed")
        build_idx = call_log.index("build_called")
        assert session_idx < build_idx, (
            f"Session must be closed before build() is called. "
            f"Call order: {call_log}"
        )
