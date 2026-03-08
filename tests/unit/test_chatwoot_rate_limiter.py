"""
Unit tests for Chatwoot rate limiter — shared/chatwoot_client.py.

Tests coverage:
- _acquire_rate_limit(): normal flow (count < limit) — no sleep
- _acquire_rate_limit(): burst throttled (count > limit) — asyncio.sleep called
- _acquire_rate_limit(): limit=0 — rate limiting disabled, no Redis interaction
- _acquire_rate_limit(): Redis down — fail open (no exception raised)
- send_message(): 429 with Retry-After header — asyncio.sleep for Retry-After seconds
- _send_template_to_conversation(): 429 handling — asyncio.sleep for Retry-After seconds
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.chatwoot_client import ChatwootClient


# =============================================================================
# Helpers
# =============================================================================


def _make_client() -> ChatwootClient:
    """Return a ChatwootClient with settings mocked to safe defaults."""
    with patch("shared.chatwoot_client.get_settings") as mock_settings:
        mock_settings.return_value.CHATWOOT_API_URL = "https://app.chatwoot.com"
        mock_settings.return_value.CHATWOOT_API_TOKEN = "test-token"
        mock_settings.return_value.CHATWOOT_ACCOUNT_ID = "1"
        mock_settings.return_value.CHATWOOT_INBOX_ID = "2"
        mock_settings.return_value.CHATWOOT_RATE_LIMIT_PER_MINUTE = 60
        return ChatwootClient()


def _make_429_response(retry_after: int | None = None) -> MagicMock:
    """Build a mock httpx.Response with status 429."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 429
    if retry_after is not None:
        response.headers = {"Retry-After": str(retry_after)}
    else:
        response.headers = {}
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429 Too Many Requests",
        request=MagicMock(),
        response=response,
    )
    return response


def _make_200_response() -> MagicMock:
    """Build a mock httpx.Response with status 200."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.raise_for_status = MagicMock(return_value=None)
    response.text = '{"id": 1}'
    return response


# =============================================================================
# Tests for _acquire_rate_limit()
# =============================================================================


class TestAcquireRateLimit:
    """Tests for the _acquire_rate_limit() private method."""

    async def test_within_limit_no_sleep(self):
        """Normal flow: counter below limit → no sleep, no exception."""
        client = _make_client()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=30)  # count 30 < 60 limit
        mock_redis.expire = AsyncMock(return_value=True)

        with (
            patch("shared.chatwoot_client.get_settings") as mock_settings,
            patch("shared.chatwoot_client.get_redis_client", return_value=mock_redis),
            patch("shared.chatwoot_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.return_value.CHATWOOT_RATE_LIMIT_PER_MINUTE = 60

            await client._acquire_rate_limit()

        mock_redis.incr.assert_awaited_once()
        mock_sleep.assert_not_awaited()

    async def test_within_limit_first_incr_sets_expire(self):
        """First INCR in a minute (count==1) → EXPIRE is set to 60 seconds."""
        client = _make_client()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)

        with (
            patch("shared.chatwoot_client.get_settings") as mock_settings,
            patch("shared.chatwoot_client.get_redis_client", return_value=mock_redis),
            patch("shared.chatwoot_client.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.return_value.CHATWOOT_RATE_LIMIT_PER_MINUTE = 60

            await client._acquire_rate_limit()

        mock_redis.expire.assert_awaited_once()
        call_args = mock_redis.expire.call_args
        # Key is the first positional arg, TTL is 60
        assert call_args[0][1] == 60

    async def test_burst_throttled_sleep_called(self):
        """Counter exceeds limit → asyncio.sleep called with seconds until next minute."""
        client = _make_client()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=61)  # 61 > 60 limit
        mock_redis.expire = AsyncMock(return_value=True)

        sleep_calls = []

        async def capture_sleep(seconds):
            sleep_calls.append(seconds)

        with (
            patch("shared.chatwoot_client.get_settings") as mock_settings,
            patch("shared.chatwoot_client.get_redis_client", return_value=mock_redis),
            patch("shared.chatwoot_client.asyncio.sleep", side_effect=capture_sleep),
            patch("shared.chatwoot_client.datetime") as mock_dt,
        ):
            mock_settings.return_value.CHATWOOT_RATE_LIMIT_PER_MINUTE = 60

            # Freeze time at second=10, microsecond=0 → sleep = 60 - 10 - 0 = 50s
            fake_now = MagicMock()
            fake_now.strftime.return_value = "20260308_1000"
            fake_now.second = 10
            fake_now.microsecond = 0
            mock_dt.now.return_value = fake_now

            await client._acquire_rate_limit()

        assert len(sleep_calls) == 1
        assert sleep_calls[0] == pytest.approx(50.0, abs=0.1)

    async def test_limit_disabled_no_redis_call(self):
        """limit=0 → skip rate limiting entirely; Redis not touched."""
        client = _make_client()

        mock_redis = AsyncMock()

        with (
            patch("shared.chatwoot_client.get_settings") as mock_settings,
            patch("shared.chatwoot_client.get_redis_client", return_value=mock_redis),
        ):
            mock_settings.return_value.CHATWOOT_RATE_LIMIT_PER_MINUTE = 0

            await client._acquire_rate_limit()

        mock_redis.incr.assert_not_awaited()
        mock_redis.expire.assert_not_awaited()

    async def test_redis_down_fail_open(self):
        """Redis connection error → fail open: no exception raised, call proceeds."""
        client = _make_client()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(side_effect=ConnectionError("Redis is down"))

        with (
            patch("shared.chatwoot_client.get_settings") as mock_settings,
            patch("shared.chatwoot_client.get_redis_client", return_value=mock_redis),
            patch("shared.chatwoot_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.return_value.CHATWOOT_RATE_LIMIT_PER_MINUTE = 60

            # Must NOT raise
            await client._acquire_rate_limit()

        mock_sleep.assert_not_awaited()

    async def test_redis_key_pattern(self):
        """Redis key follows chatwoot:rate_limit:{YYYYMMDD_HHMM} pattern."""
        client = _make_client()

        captured_keys = []

        mock_redis = AsyncMock()

        async def capture_incr(key):
            captured_keys.append(key)
            return 1

        mock_redis.incr = capture_incr
        mock_redis.expire = AsyncMock(return_value=True)

        with (
            patch("shared.chatwoot_client.get_settings") as mock_settings,
            patch("shared.chatwoot_client.get_redis_client", return_value=mock_redis),
            patch("shared.chatwoot_client.asyncio.sleep", new_callable=AsyncMock),
            patch("shared.chatwoot_client.datetime") as mock_dt,
        ):
            mock_settings.return_value.CHATWOOT_RATE_LIMIT_PER_MINUTE = 60

            fake_now = MagicMock()
            fake_now.strftime.return_value = "20260308_1030"
            fake_now.second = 0
            fake_now.microsecond = 0
            mock_dt.now.return_value = fake_now

            await client._acquire_rate_limit()

        assert len(captured_keys) == 1
        assert captured_keys[0] == "chatwoot:rate_limit:20260308_1030"


# =============================================================================
# Tests for send_message() 429 handling
# =============================================================================


class TestSendMessage429Handling:
    """Tests for 429 Retry-After behaviour in send_message()."""

    async def test_429_with_retry_after_sleeps_correct_duration(self):
        """
        When Chatwoot returns 429 with Retry-After: 30, asyncio.sleep(30) is called
        before the error propagates.
        """
        client = _make_client()
        sleep_calls = []

        async def capture_sleep(seconds):
            sleep_calls.append(seconds)

        # Mock _acquire_rate_limit to be a no-op for isolation
        with (
            patch.object(client, "_acquire_rate_limit", new_callable=AsyncMock),
            patch("shared.chatwoot_client.asyncio.sleep", side_effect=capture_sleep),
        ):
            # Patch the httpx.AsyncClient.post to return 429 with Retry-After
            mock_response = _make_429_response(retry_after=30)
            mock_http_client = AsyncMock()
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_http_client.post = AsyncMock(return_value=mock_response)

            with patch("shared.chatwoot_client.httpx.AsyncClient", return_value=mock_http_client):
                result = await client.send_message(
                    customer_phone="+34612345678",
                    message="Hola",
                    conversation_id=42,
                )

        # Sleep was called with the Retry-After value
        assert 30 in sleep_calls
        # The 429 exception propagated → send_message returns False
        assert result is False

    async def test_429_without_retry_after_defaults_to_60(self):
        """When Retry-After header is absent, default sleep of 60s is used."""
        client = _make_client()
        sleep_calls = []

        async def capture_sleep(seconds):
            sleep_calls.append(seconds)

        with (
            patch.object(client, "_acquire_rate_limit", new_callable=AsyncMock),
            patch("shared.chatwoot_client.asyncio.sleep", side_effect=capture_sleep),
        ):
            mock_response = _make_429_response(retry_after=None)
            mock_http_client = AsyncMock()
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_http_client.post = AsyncMock(return_value=mock_response)

            with patch("shared.chatwoot_client.httpx.AsyncClient", return_value=mock_http_client):
                result = await client.send_message(
                    customer_phone="+34612345678",
                    message="Hola",
                    conversation_id=42,
                )

        assert 60 in sleep_calls
        assert result is False

    async def test_200_response_no_429_sleep(self):
        """Successful 200 response → no 429-related sleep is called."""
        client = _make_client()
        sleep_calls = []

        async def capture_sleep(seconds):
            sleep_calls.append(seconds)

        with (
            patch.object(client, "_acquire_rate_limit", new_callable=AsyncMock),
            patch("shared.chatwoot_client.asyncio.sleep", side_effect=capture_sleep),
        ):
            mock_response = _make_200_response()
            mock_response.json.return_value = {"id": 1}
            mock_http_client = AsyncMock()
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_http_client.post = AsyncMock(return_value=mock_response)

            with patch("shared.chatwoot_client.httpx.AsyncClient", return_value=mock_http_client):
                result = await client.send_message(
                    customer_phone="+34612345678",
                    message="Hola",
                    conversation_id=42,
                )

        assert result is True
        assert sleep_calls == []


# =============================================================================
# Tests for _send_template_to_conversation() 429 handling
# =============================================================================


class TestSendTemplateToConversation429Handling:
    """Tests for 429 Retry-After behaviour in _send_template_to_conversation()."""

    async def test_429_with_retry_after_sleeps_correct_duration(self):
        """429 in template send → sleeps Retry-After seconds then re-raises."""
        client = _make_client()
        sleep_calls = []

        async def capture_sleep(seconds):
            sleep_calls.append(seconds)

        with (
            patch.object(client, "_acquire_rate_limit", new_callable=AsyncMock),
            patch("shared.chatwoot_client.asyncio.sleep", side_effect=capture_sleep),
        ):
            mock_response = _make_429_response(retry_after=45)
            mock_http_client = AsyncMock()
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_http_client.post = AsyncMock(return_value=mock_response)

            with patch("shared.chatwoot_client.httpx.AsyncClient", return_value=mock_http_client):
                with pytest.raises(httpx.HTTPStatusError):
                    await client._send_template_to_conversation(
                        conversation_id=99,
                        customer_phone="+34612345678",
                        template_name="appointment_confirmation_48h",
                        body_params={"1": "María"},
                    )

        assert 45 in sleep_calls

    async def test_200_response_returns_true(self):
        """Successful 200 response → returns True without sleep."""
        client = _make_client()

        with (
            patch.object(client, "_acquire_rate_limit", new_callable=AsyncMock),
            patch("shared.chatwoot_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_response = _make_200_response()
            mock_http_client = AsyncMock()
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_http_client.post = AsyncMock(return_value=mock_response)

            with patch("shared.chatwoot_client.httpx.AsyncClient", return_value=mock_http_client):
                result = await client._send_template_to_conversation(
                    conversation_id=99,
                    customer_phone="+34612345678",
                    template_name="appointment_confirmation_48h",
                    body_params={"1": "María"},
                )

        assert result is True
        mock_sleep.assert_not_awaited()
