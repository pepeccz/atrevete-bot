"""
Unit tests for get_sync_redis_client() password handling in the archiver worker.

TDD RED phase — written before the fix. Asserts that the sync client passes
REDIS_PASSWORD to redis.from_url when the setting is configured, and omits it
when the setting is empty — matching the shared async client pattern in
shared/redis_client.py.

Root cause: conversation_archiver.py get_sync_redis_client() never passed the
password to from_url, causing AuthenticationError on every Redis scan in prod
and leaving conversation_history permanently empty.
"""

from unittest.mock import MagicMock, patch


def _patch_settings(password: str):
    """Return a mock Settings object with the given REDIS_PASSWORD."""
    mock_settings = MagicMock()
    mock_settings.REDIS_URL = "redis://redis:6379/0"
    mock_settings.REDIS_PASSWORD = password
    return mock_settings


class TestGetSyncRedisClientAuth:
    """Password forwarding behaviour for get_sync_redis_client()."""

    def test_password_passed_when_configured(self):
        """When REDIS_PASSWORD is set, from_url must receive password= kwarg."""
        mock_client = MagicMock()
        mock_settings = _patch_settings("supersecret")

        with patch(
            "agent.workers.conversation_archiver.get_settings",
            return_value=mock_settings,
        ), patch(
            "agent.workers.conversation_archiver.redis.from_url",
            return_value=mock_client,
        ) as mock_from_url:
            from agent.workers.conversation_archiver import get_sync_redis_client

            result = get_sync_redis_client()

        mock_from_url.assert_called_once()
        _, kwargs = mock_from_url.call_args
        assert kwargs.get("password") == "supersecret", (
            "from_url must be called with password=<REDIS_PASSWORD> when the setting is set"
        )

    def test_decode_responses_false_preserved(self):
        """decode_responses=False must always be passed (binary checkpoint data)."""
        mock_client = MagicMock()
        mock_settings = _patch_settings("anypass")

        with patch(
            "agent.workers.conversation_archiver.get_settings",
            return_value=mock_settings,
        ), patch(
            "agent.workers.conversation_archiver.redis.from_url",
            return_value=mock_client,
        ) as mock_from_url:
            from agent.workers.conversation_archiver import get_sync_redis_client

            get_sync_redis_client()

        _, kwargs = mock_from_url.call_args
        assert kwargs.get("decode_responses") is False, (
            "decode_responses must remain False to handle binary checkpoint data"
        )

    def test_retry_on_timeout_true_preserved(self):
        """retry_on_timeout=True must always be passed for resilience."""
        mock_client = MagicMock()
        mock_settings = _patch_settings("anypass")

        with patch(
            "agent.workers.conversation_archiver.get_settings",
            return_value=mock_settings,
        ), patch(
            "agent.workers.conversation_archiver.redis.from_url",
            return_value=mock_client,
        ) as mock_from_url:
            from agent.workers.conversation_archiver import get_sync_redis_client

            get_sync_redis_client()

        _, kwargs = mock_from_url.call_args
        assert kwargs.get("retry_on_timeout") is True, (
            "retry_on_timeout must remain True for transient network failures"
        )

    def test_no_password_kwarg_when_empty(self):
        """When REDIS_PASSWORD is empty string, password must NOT be forwarded."""
        mock_client = MagicMock()
        mock_settings = _patch_settings("")

        with patch(
            "agent.workers.conversation_archiver.get_settings",
            return_value=mock_settings,
        ), patch(
            "agent.workers.conversation_archiver.redis.from_url",
            return_value=mock_client,
        ) as mock_from_url:
            from agent.workers.conversation_archiver import get_sync_redis_client

            get_sync_redis_client()

        _, kwargs = mock_from_url.call_args
        assert "password" not in kwargs, (
            "password kwarg must be omitted when REDIS_PASSWORD is empty "
            "(keeps local/no-auth dev working)"
        )

    def test_no_password_kwarg_when_none(self):
        """When REDIS_PASSWORD is None/falsy, password must NOT be forwarded."""
        mock_settings = MagicMock()
        mock_settings.REDIS_URL = "redis://redis:6379/0"
        mock_settings.REDIS_PASSWORD = None

        with patch(
            "agent.workers.conversation_archiver.get_settings",
            return_value=mock_settings,
        ), patch(
            "agent.workers.conversation_archiver.redis.from_url",
            return_value=MagicMock(),
        ) as mock_from_url:
            from agent.workers.conversation_archiver import get_sync_redis_client

            get_sync_redis_client()

        _, kwargs = mock_from_url.call_args
        assert "password" not in kwargs, (
            "password kwarg must be omitted when REDIS_PASSWORD is None"
        )
