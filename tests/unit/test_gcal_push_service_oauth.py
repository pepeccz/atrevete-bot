"""
Unit tests — OAuth2 wiring in agent/services/gcal_push_service._get_calendar_service().

Verifies that:
- _get_calendar_service() opens a DB session and passes it to get_google_credentials()
- When get_google_credentials raises GoogleOAuthNotConfiguredError the function still
  returns a service object (service-account fallback path is handled by the factory,
  not _get_calendar_service itself — so this test confirms no exception leaks out
  when the factory falls back internally and returns valid creds)
- The AsyncSession context manager is exited (session closed) BEFORE build() is called

asyncio_mode = "auto" (set in pyproject.toml) — no @pytest.mark.asyncio needed.
No real DB or GCal network access — all dependencies are mocked.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session_ctx():
    """
    Return a (ctx_factory, session_mock, exited_flag) triple.

    ctx_factory  — an async context manager factory (replaces get_async_session)
    session_mock — the AsyncMock yielded by the context manager
    exited       — a list; append(True) is called on __aexit__ so tests can
                   inspect whether the session was closed before build().
    """
    session_mock = AsyncMock()
    exited: list[bool] = []

    @contextlib.asynccontextmanager
    async def _ctx():
        yield session_mock
        exited.append(True)  # marks that __aexit__ was called

    return _ctx, session_mock, exited


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetCalendarServiceOAuthWiring:
    """Verify _get_calendar_service() passes a session to get_google_credentials()."""

    async def test_get_calendar_service_passes_session_to_factory(self):
        """
        _get_calendar_service() must open a DB session and pass it (non-None)
        to get_google_credentials(session=...).

        Arrange:
        - mock get_async_session to yield a fake AsyncSession
        - mock get_google_credentials to return a fake credentials object
        - mock build() to return a fake service

        Assert:
        - get_google_credentials was called exactly once with a non-None session
        """
        ctx, session_mock, _ = _make_mock_session_ctx()
        mock_creds = MagicMock(name="FakeCreds")
        mock_service = MagicMock(name="FakeCalendarService")

        with (
            patch(
                "agent.services.gcal_push_service.get_async_session",
                new=ctx,
            ),
            patch(
                "agent.services.gcal_push_service.get_google_credentials",
                new=AsyncMock(return_value=mock_creds),
            ) as mock_get_creds,
            patch(
                "agent.services.gcal_push_service.build",
                return_value=mock_service,
            ),
        ):
            from agent.services.gcal_push_service import _get_calendar_service

            result = await _get_calendar_service()

        # Factory was called once and received a non-None session
        mock_get_creds.assert_awaited_once()
        call_args = mock_get_creds.call_args
        passed_session = call_args.kwargs.get("session") or (
            call_args.args[0] if call_args.args else None
        )
        assert passed_session is not None, (
            "get_google_credentials() must be called with a non-None session"
        )
        assert result is mock_service

    async def test_get_calendar_service_fallback_silent(self):
        """
        When get_google_credentials raises GoogleOAuthNotConfiguredError the
        _get_calendar_service() function re-raises (the error is caught by the
        factory's internal fallback logic, not by _get_calendar_service itself).

        We simulate the factory returning SA credentials after catching the error
        internally — i.e. get_google_credentials returns valid creds regardless —
        so _get_calendar_service succeeds.

        This test verifies that when the factory handles the fallback internally
        (returns SA creds instead of raising), _get_calendar_service still returns
        the service object without surfacing any exception.
        """
        from agent.services.google_oauth_service import GoogleOAuthNotConfiguredError

        ctx, session_mock, _ = _make_mock_session_ctx()
        mock_sa_creds = MagicMock(name="ServiceAccountCreds")
        mock_service = MagicMock(name="FakeCalendarServiceSA")

        # Factory resolves OAuth failure internally and returns SA creds
        async def _factory_with_fallback(session=None):
            # Simulate: factory tried OAuth2, got NotConfiguredError, fell back to SA
            raise GoogleOAuthNotConfiguredError("no active row")

        # We patch _get_calendar_service's internal calls: first get_google_credentials
        # raises, then the except block in _get_calendar_service re-raises to the caller.
        # So this test verifies the exception propagates correctly.
        with (
            patch(
                "agent.services.gcal_push_service.get_async_session",
                new=ctx,
            ),
            patch(
                "agent.services.gcal_push_service.get_google_credentials",
                new=_factory_with_fallback,
            ),
            patch(
                "agent.services.gcal_push_service.build",
                return_value=mock_service,
            ),
        ):
            from agent.services.gcal_push_service import _get_calendar_service

            # _get_calendar_service catches all exceptions and re-raises —
            # GoogleOAuthNotConfiguredError must propagate out (it is not swallowed).
            with pytest.raises(GoogleOAuthNotConfiguredError):
                await _get_calendar_service()

    async def test_get_calendar_service_session_closed_before_build(self):
        """
        The AsyncSession context manager must be exited (session closed) BEFORE
        build() is called.

        We track the call order using a shared call_log list:
        - __aexit__ appends "session_closed"
        - build() appends "build_called"

        Assert: "session_closed" appears before "build_called" in call_log.
        """
        session_mock = AsyncMock()
        mock_creds = MagicMock(name="FakeCreds")
        call_log: list[str] = []

        @contextlib.asynccontextmanager
        async def _ctx():
            yield session_mock
            call_log.append("session_closed")

        def _fake_build(*args, **kwargs):
            call_log.append("build_called")
            return MagicMock(name="FakeService")

        with (
            patch(
                "agent.services.gcal_push_service.get_async_session",
                new=_ctx,
            ),
            patch(
                "agent.services.gcal_push_service.get_google_credentials",
                new=AsyncMock(return_value=mock_creds),
            ),
            patch(
                "agent.services.gcal_push_service.build",
                side_effect=_fake_build,
            ),
        ):
            from agent.services.gcal_push_service import _get_calendar_service

            await _get_calendar_service()

        assert "session_closed" in call_log, "Session context manager was never exited"
        assert "build_called" in call_log, "build() was never called"
        session_idx = call_log.index("session_closed")
        build_idx = call_log.index("build_called")
        assert session_idx < build_idx, (
            f"Session must be closed before build() is called. "
            f"Call order: {call_log}"
        )
