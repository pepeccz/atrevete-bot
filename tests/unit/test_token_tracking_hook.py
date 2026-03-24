"""Unit tests for BaseModeNode._track_token_usage hook."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import BaseModeNode


class _DummyMode(BaseModeNode):
    @property
    def mode_name(self) -> str:
        return "GENERAL"

    async def handle(self, state, intent):
        return {"last_node": "dummy"}


def _make_node() -> _DummyMode:
    """Create a DummyMode with mocked LLM."""
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm)
    return _DummyMode(tools=[], llm_client=llm)


@pytest.mark.asyncio
async def test_track_extracts_usage_metadata():
    """Should extract input/output tokens from usage_metadata dict."""
    node = _make_node()
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 500, "output_tokens": 200},
        content="Hello",
    )

    with patch(
        "agent.services.token_tracking.record_token_usage", new_callable=AsyncMock
    ) as mock_record:
        await node._track_token_usage(response)
        mock_record.assert_called_once_with(input_tokens=500, output_tokens=200)


@pytest.mark.asyncio
async def test_track_fallback_response_metadata():
    """Should fall back to response_metadata.token_usage (OpenAI format)."""
    node = _make_node()
    # Create a response with NO usage_metadata but with response_metadata
    response = MagicMock(spec=[])
    response.response_metadata = {
        "token_usage": {
            "prompt_tokens": 300,
            "completion_tokens": 150,
        }
    }
    response.content = "Hello"

    with patch(
        "agent.services.token_tracking.record_token_usage", new_callable=AsyncMock
    ) as mock_record:
        await node._track_token_usage(response)
        mock_record.assert_called_once_with(input_tokens=300, output_tokens=150)


@pytest.mark.asyncio
async def test_track_skips_when_no_usage():
    """Should silently skip when no usage metadata exists."""
    node = _make_node()
    response = SimpleNamespace(content="Hello")

    with patch(
        "agent.services.token_tracking.record_token_usage", new_callable=AsyncMock
    ) as mock_record:
        await node._track_token_usage(response)
        mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_track_skips_zero_tokens():
    """Should not call record when both tokens are 0."""
    node = _make_node()
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 0, "output_tokens": 0},
        content="Hello",
    )

    with patch(
        "agent.services.token_tracking.record_token_usage", new_callable=AsyncMock
    ) as mock_record:
        await node._track_token_usage(response)
        mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_track_handles_none_usage_metadata():
    """Should handle usage_metadata=None gracefully."""
    node = _make_node()
    response = SimpleNamespace(
        usage_metadata=None,
        response_metadata=None,
        content="Hello",
    )

    with patch(
        "agent.services.token_tracking.record_token_usage", new_callable=AsyncMock
    ) as mock_record:
        await node._track_token_usage(response)
        mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_track_never_raises():
    """Errors in tracking should be swallowed — fire-and-forget."""
    node = _make_node()
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 100, "output_tokens": 50},
        content="Hello",
    )

    with patch(
        "agent.services.token_tracking.record_token_usage",
        new_callable=AsyncMock,
        side_effect=Exception("DB down"),
    ):
        # Should NOT raise
        await node._track_token_usage(response)


@pytest.mark.asyncio
async def test_track_handles_non_dict_usage_metadata():
    """Should handle usage_metadata that is not a dict."""
    node = _make_node()
    response = SimpleNamespace(
        usage_metadata="not a dict",
        response_metadata=None,
        content="Hello",
    )

    with patch(
        "agent.services.token_tracking.record_token_usage", new_callable=AsyncMock
    ) as mock_record:
        await node._track_token_usage(response)
        mock_record.assert_not_called()
